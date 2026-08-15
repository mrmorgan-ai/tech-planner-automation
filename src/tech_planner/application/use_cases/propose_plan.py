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

from tech_planner.application.events import (
    AwaitingApproval,
    Event,
    PassKind,
    PlanValidated,
    ProposalReady,
    RunFailed,
)
from tech_planner.application.ports.agent_gateway import AgentGateway, AgentRequest
from tech_planner.application.ports.context_repository import ContextRepository
from tech_planner.application.ports.prompt_repository import PromptRepository
from tech_planner.application.ports.session_repository import SessionRepository
from tech_planner.application.ports.settings_provider import SettingsProvider
from tech_planner.domain.model.planning_session import SessionStatus
from tech_planner.domain.rules.planning_rules import validate


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
        )

        proposal = None
        async for event in self.agent.run(request):
            yield event
            if isinstance(event, ProposalReady):
                proposal = event.proposal
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

        report = validate(proposal, settings.planning_policy())
        session.record_proposal(proposal, report)
        self.sessions.save(session)

        yield PlanValidated(report=report, approvable=report.is_approvable)
        yield AwaitingApproval(session_id=session.id, item_count=len(proposal.items))
