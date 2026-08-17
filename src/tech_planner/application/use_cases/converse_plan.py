"""Planning as a conversation rather than a single question.

`ProposePlan` next door asks once and is done. That is the right shape for the
create pass and a poor one for planning, where the first answer is rarely the
last: a story needs splitting, a sprint is wrong, the requirement turns out to
mean something else. Starting over for each of those throws away everything the
agent learned — the iterations it queried, the code it read — and invites it to
reach different conclusions the second time.

So planning holds one runtime session open and takes turns in it. What does
*not* change is the gate: this conversation runs for its whole life with the
backend's write tools denied, because a process's permissions cannot be altered
once it is running. Creating remains a separate pass, launched only after an
approval, which is exactly the property that makes it safe to leave a planning
session open for as long as the user likes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from tech_planner.application.events import (
    AwaitingApproval,
    Event,
    PassKind,
    PlanValidated,
    ProposalReady,
    RunFailed,
    TurnEnded,
)
from tech_planner.application.ports.agent_gateway import (
    AgentGateway,
    AgentRequest,
    Conversation,
)
from tech_planner.application.ports.context_repository import ContextRepository
from tech_planner.application.ports.prompt_repository import PromptRepository
from tech_planner.application.ports.session_repository import SessionRepository
from tech_planner.application.ports.settings_provider import SettingsProvider
from tech_planner.application.settings import Settings
from tech_planner.domain.model.planning_session import PlanningSession
from tech_planner.domain.rules.planning_rules import validate
from tech_planner.domain.rules.violations import RuleViolation, ValidationReport


@dataclass(frozen=True, slots=True)
class ConversePlan:
    """Opens planning conversations."""

    agent: AgentGateway
    sessions: SessionRepository
    prompts: PromptRepository
    context: ContextRepository
    settings: SettingsProvider

    async def __call__(self, session_id: str, requirement: str) -> PlanningConversation:
        session = self.sessions.get(session_id)
        settings = self.settings.load()
        prompt = self.prompts.assemble()

        session.requirement = requirement
        session.prompt_revision = prompt.revision
        self.sessions.save(session)

        request = AgentRequest(
            session_id=session.id,
            kind=PassKind.PROPOSE,
            prompt=requirement,
            system_prompt=prompt.text,
            context_files=tuple(f.path for f in self.context.list()),
            scope=session.scope,
            buffer_factor=session.buffer_factor,
            capacity_hours=session.capacity_hours,
        )
        conversation = await self.agent.converse(request)
        return PlanningConversation(
            session=session,
            conversation=conversation,
            sessions=self.sessions,
            settings=settings,
        )


@dataclass(slots=True)
class PlanningConversation:
    """A live planning session, with the rules applied to every turn.

    The rules run per *turn*, not per session. A revised plan is a new plan and
    gets judged as one — which is the point of asking for a revision, and the
    reason the approval state is re-derived each time rather than remembered.
    """

    session: PlanningSession
    conversation: Conversation
    sessions: SessionRepository
    settings: Settings

    async def send(self, text: str) -> None:
        """Take another turn: a correction, a question, a fresh requirement."""
        await self.conversation.send(text)

    async def close(self) -> None:
        await self.conversation.close()

    async def events(self) -> AsyncIterator[Event]:
        proposal = None
        notes: tuple[RuleViolation, ...] = ()

        async for event in self.conversation.events():
            yield event

            if isinstance(event, ProposalReady):
                proposal = event.proposal
                notes = event.notes
                continue

            if isinstance(event, RunFailed):
                self.session.fail(event.reason)
                self.sessions.save(self.session)
                return

            if not isinstance(event, TurnEnded):
                continue

            if proposal is None:
                # A conversational turn — the agent asked something, or
                # answered in words. Nothing to validate, and nothing about
                # the session's state has changed.
                continue

            report = validate(
                proposal,
                self.settings.planning_policy(
                    scope=self.session.scope, capacity_hours=self.session.capacity_hours
                ),
            )
            self.session.record_proposal(proposal, report)
            self.sessions.save(self.session)

            # Parse-time corrections belong in the same report the user reads,
            # not in a separate channel they might miss.
            merged = ValidationReport(violations=notes + report.violations)
            yield PlanValidated(report=merged, approvable=merged.is_approvable)
            yield AwaitingApproval(session_id=self.session.id, item_count=len(proposal.items))

            # Each turn is judged on its own plan, so the next one starts from
            # nothing rather than re-validating the last answer.
            proposal, notes = None, ()
