"""Pass 1: turn a requirement into a proposed breakdown, and check it.

Nothing here can write to a work-tracking backend. That is not a convention
this module observes — the pass it asks for runs with the backend's mutating
tools denied, so creation is unavailable to the agent regardless of what the
requirement text asks for.

What this use case adds on top of the agent's answer is the part the spec calls
mandatory and models are unreliable at across thirty tasks: the x1.30
arithmetic, the two-day task ceiling, sprint fit, and Definition-of-Done
coverage are recomputed here, in code, and reported before anyone approves.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from planify.application.events import (
    AwaitingApproval,
    Event,
    PassKind,
    PlanValidated,
    ProposalReady,
    RunFailed,
)
from planify.application.ports.agent_gateway import AgentGateway, AgentRequest
from planify.application.ports.context_repository import ContextRepository
from planify.application.ports.prompt_repository import PromptRepository
from planify.application.ports.session_repository import SessionRepository
from planify.application.ports.settings_provider import SettingsProvider
from planify.domain.model.planning_session import SessionStatus
from planify.domain.rules.planning_rules import validate
from planify.domain.rules.violations import RuleViolation, ValidationReport


@dataclass(frozen=True, slots=True)
class ProposePlan:
    agent: AgentGateway
    sessions: SessionRepository
    prompts: PromptRepository
    context: ContextRepository
    settings: SettingsProvider

    async def __call__(self, session_id: str, requirement: str) -> AsyncIterator[Event]:
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
            # A second requirement in the same session continues the
            # conversation, so the agent can revise rather than start over.
            resume=session.status is not SessionStatus.DRAFTING,
            scope=session.scope,
            buffer_factor=session.buffer_factor,
            capacity_hours=session.capacity_hours,
        )

        proposal = None
        notes: tuple[RuleViolation, ...] = ()
        async for event in self.agent.run(request):
            yield event
            if isinstance(event, ProposalReady):
                proposal = event.proposal
                notes = event.notes
            elif isinstance(event, RunFailed):
                session.fail(event.reason)
                self.sessions.save(session)
                return

        if proposal is None:
            # The gateway contract promises a terminal event. If we get here it
            # was broken, and silence must never be mistaken for success.
            reason = "the agent run ended without producing a plan"
            session.fail(reason)
            self.sessions.save(session)
            yield RunFailed(reason=reason, retryable=True)
            return

        report = validate(
            proposal,
            settings.planning_policy(
                scope=session.scope, capacity_hours=session.capacity_hours
            ),
        )
        session.record_proposal(proposal, report)
        self.sessions.save(session)

        # Parse-time corrections belong in the same report the user reviews,
        # not in a separate channel they might not read.
        report = ValidationReport(violations=notes + report.violations)
        yield PlanValidated(report=report, approvable=report.is_approvable)
        yield AwaitingApproval(session_id=session.id, item_count=len(proposal.items))
