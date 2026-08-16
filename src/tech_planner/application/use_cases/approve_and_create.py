"""Pass 2: record the user's verdict and, only on a yes, write the plan.

This is the only path in the codebase that leads to a run with the backend's
mutating tools unlocked, and it is guarded twice over. `PlanningSession.decide`
refuses to approve a plan that breaks a mandatory rule, and `begin_creation`
refuses to run from any state but an approved one — so the argv builder that
unlocks those tools can only ever be reached with a genuine approval behind it.

The agent's own permissions are the other half. Neither guard is trusted alone.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from tech_planner.application.events import (
    ApprovalRecorded,
    CreationReported,
    Event,
    PassKind,
    RunFailed,
)
from tech_planner.application.ports.agent_gateway import AgentGateway, AgentRequest
from tech_planner.application.ports.prompt_repository import PromptRepository
from tech_planner.application.ports.session_repository import SessionRepository
from tech_planner.domain.model.approval import ApprovalDecision
from tech_planner.domain.model.estimate import format_hours
from tech_planner.domain.model.plan_proposal import PlanProposal
from tech_planner.domain.model.work_item import Task, UserStory


@dataclass(frozen=True, slots=True)
class ApproveAndCreate:
    agent: AgentGateway
    sessions: SessionRepository
    prompts: PromptRepository

    async def __call__(
        self, session_id: str, decision: ApprovalDecision
    ) -> AsyncIterator[Event]:
        session = self.sessions.get(session_id)

        # Raises if the plan still breaks a mandatory rule. The user may
        # override a warning; an error is not theirs to wave through.
        session.decide(decision)
        self.sessions.save(session)
        yield ApprovalRecorded(
            session_id=session.id, approved=decision.approved, note=decision.note
        )
        if not decision.approved:
            return

        assert session.proposal is not None  # guaranteed by the PROPOSED state
        session.begin_creation()
        self.sessions.save(session)

        request = AgentRequest(
            session_id=session.id,
            kind=PassKind.CREATE,
            prompt=creation_instruction(session.proposal),
            system_prompt=self.prompts.assemble().text,
            # Always resume: the agent already researched the iterations and
            # area paths during the propose pass, and repeating that work would
            # invite it to resolve them differently the second time.
            resume=True,
            scope=session.scope,
            buffer_factor=session.buffer_factor,
        )

        created = None
        async for event in self.agent.run(request):
            yield event
            if isinstance(event, CreationReported):
                created = event.items
            elif isinstance(event, RunFailed):
                session.fail(event.reason)
                self.sessions.save(session)
                return

        if not created:
            # A create pass that reports nothing is the worst outcome to guess
            # about: items may or may not exist. Say so rather than assume.
            reason = (
                "the create pass ended without reporting any work items; "
                "check the backend before retrying, as some may have been created"
            )
            session.fail(reason)
            self.sessions.save(session)
            yield RunFailed(reason=reason, retryable=False)
            return

        session.record_creation(created)
        self.sessions.save(session)


def creation_instruction(proposal: PlanProposal) -> str:
    """Restate the approved plan as the turn that creates it.

    The agent is resuming the session that produced this plan, so in principle
    it already has it. Restating it anyway makes the approved scope explicit in
    the turn that acts on it: what gets written is what was validated, not
    whatever the model still remembers.
    """
    lines = [
        "The user approved the plan below. Create exactly these work items in "
        "the configured backend — nothing more, nothing fewer, no edits.",
        "",
    ]
    lines.extend(_render(proposal))
    lines += [
        "",
        "Create parents before children and link each child to its parent.",
        "Put the final (buffered) hours on each Task as both the original "
        "estimate and the remaining work; put story points on the User Story. "
        "Never put both on the same item.",
        "Then report every created item with its plan ref and the id the "
        "backend assigned.",
    ]
    return "\n".join(lines)


def _render(proposal: PlanProposal, ref: str | None = None, depth: int = 0) -> list[str]:
    items = proposal.roots() if ref is None else proposal.children_of(ref)
    lines: list[str] = []
    for item in items:
        lines.append(f"{'  ' * depth}- [{item.ref}] {item.type}: {item.title}{_detail(item)}")
        lines.extend(_render(proposal, item.ref, depth + 1))
    return lines


def _detail(item: object) -> str:
    if isinstance(item, Task):
        return (
            f" — {format_hours(item.effort.final_hours)}h final "
            f"({format_hours(item.effort.base_hours)}h base), {item.kind}"
        )
    if isinstance(item, UserStory) and item.story_points is not None:
        return f" — {item.story_points} points"
    return ""
