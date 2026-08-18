"""Turning events and plans into terminal output.

Separate from the command wiring so the HTTP adapter in the next phase can
reuse the plan rendering while serializing the events differently.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable

from planify.application.events import (
    AgentRetrying,
    ApprovalRecorded,
    AssistantDelta,
    AssistantMessage,
    AwaitingApproval,
    CreationReported,
    Event,
    Notice,
    PlanValidated,
    ProposalReady,
    RunFailed,
    RunStarted,
    ToolFinished,
    ToolStarted,
)
from decimal import Decimal

from planify.domain.model.estimate import DEFAULT_BUFFER_FACTOR, format_hours
from planify.domain.model.plan_proposal import PlanProposal
from planify.domain.model.work_item import Task, UserStory
from planify.domain.rules.violations import RuleViolation, Severity

_SEVERITY_MARK = {Severity.ERROR: "✗", Severity.WARNING: "!", Severity.INFO: "·"}


def render_event(event: Event) -> None:
    """Print one event as it happens. Deltas stream inline; everything else is a line."""
    match event:
        case AssistantDelta():
            sys.stdout.write(event.text)
            sys.stdout.flush()
        case AssistantMessage():
            _line()
        case RunStarted():
            servers = ", ".join(event.mcp_servers) or "none"
            _line(f"· {event.kind} pass · model {event.model or 'default'}")
            _line(f"· connected: {servers}")
        case ToolStarted():
            _line(f"  → {event.name} {event.detail}".rstrip())
        case ToolFinished():
            if not event.ok:
                _line(f"  ← {event.name} failed: {event.detail}")
        case AgentRetrying():
            _line(f"· waiting: {event.reason}")
        case Notice():
            _line(f"· {event.message}")
        case PlanValidated():
            _line()
            render_violations(event.report.violations)
        case AwaitingApproval():
            _line()
        case ApprovalRecorded():
            _line("· approved" if event.approved else "· rejected — nothing was created")
        case ProposalReady() | CreationReported():
            pass
        case RunFailed():
            _line(f"\n✗ {event.reason}")
        case _:
            pass


def render_plan(proposal: PlanProposal, buffer_factor: Decimal | None = None) -> None:
    _line("\nProposed plan")
    _line("─" * 60)
    _render_branch(proposal)
    _line("─" * 60)
    if not proposal.tasks:
        # Above sprint level there are no hours to total, so summarising them
        # would be inventing a number.
        _line(f"{len(proposal.items)} items · sized in story points")
        return

    factor = buffer_factor if buffer_factor is not None else DEFAULT_BUFFER_FACTOR
    # The total is the sum of the per-task rounded figures, not the base total
    # re-multiplied. Each task's hours go on its own work item and have to be a
    # usable number there, so the rounding happens per task and the total is
    # whatever those add up to — which is what will actually be on the board.
    _line(
        f"{len(proposal.tasks)} tasks · "
        f"{format_hours(proposal.total_base_hours)}h base · "
        f"{format_hours(proposal.total_final_hours)}h buffered (x{format_hours(factor)})"
    )


def _render_branch(proposal: PlanProposal, ref: str | None = None, depth: int = 0) -> None:
    children = proposal.roots() if ref is None else proposal.children_of(ref)
    for item in children:
        indent = "  " * depth
        _line(f"{indent}{item.type}  {item.title}{_suffix(proposal, item)}")
        _render_branch(proposal, item.ref, depth + 1)


def _suffix(proposal: PlanProposal, item: object) -> str:
    if isinstance(item, Task):
        return (
            f"   [{format_hours(item.effort.base_hours)}h → "
            f"{format_hours(item.effort.final_hours)}h · {item.kind}]"
        )
    if isinstance(item, UserStory):
        total = proposal.final_hours_of(item.ref)
        points = f"{item.story_points} pts · " if item.story_points else ""
        return f"   [{points}{format_hours(total)}h total]"
    return ""


def render_violations(violations: Iterable[RuleViolation]) -> None:
    violations = list(violations)
    if not violations:
        _line("✓ the plan breaks none of the planning rules")
        return

    errors = [v for v in violations if v.severity is Severity.ERROR]
    _line(f"{len(violations)} finding(s), {len(errors)} blocking:")
    for violation in violations:
        mark = _SEVERITY_MARK.get(violation.severity, "·")
        where = f"[{violation.item_ref}] " if violation.item_ref else ""
        _line(f"  {mark} {where}{violation.message}")


def _line(text: str = "") -> None:
    print(text, flush=True)
