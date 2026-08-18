"""Turning events and domain objects into JSON the browser can read.

The counterpart of `cli/render.py`: same event vocabulary, different output.
Written out by hand rather than derived with `dataclasses.asdict`, for two
reasons. The event stream is a contract the web app codes against, and deriving
it would mean a field rename in the domain silently breaking the UI. And hours
are `Decimal` end to end — `asdict` would hand them to a JSON encoder that
either refuses them or, worse, converts them to a float and undoes the exact
arithmetic the domain exists to protect.

Every hour figure therefore crosses the wire as a **string**. JSON numbers are
IEEE doubles in every browser, so a number here would be a lossy number there.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

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
    TurnEnded,
)
from planify.domain.model.estimate import format_hours
from planify.domain.model.plan_proposal import PlanProposal
from planify.domain.model.planning_session import PlanningSession
from planify.domain.model.work_item import AnyWorkItem, Task
from planify.domain.rules.violations import ValidationReport


def event_message(event: Event) -> tuple[str, dict[str, Any]]:
    """One event as `(name, payload)`. The name is the SSE event type."""
    match event:
        case AssistantDelta():
            return "assistant_delta", {"text": event.text}
        case AssistantMessage():
            return "assistant_message", {"text": event.text}
        case RunStarted():
            return "run_started", {
                "session_id": event.session_id,
                "kind": str(event.kind),
                "model": event.model,
                "mcp_servers": list(event.mcp_servers),
                "resumed": event.resumed,
            }
        case ToolStarted():
            return "tool_started", {"name": event.name, "detail": event.detail}
        case ToolFinished():
            return "tool_finished", {
                "name": event.name,
                "ok": event.ok,
                "detail": event.detail,
            }
        case AgentRetrying():
            return "agent_retrying", {"reason": event.reason, "attempt": event.attempt}
        case ProposalReady():
            return "proposal_ready", {"proposal": proposal_payload(event.proposal)}
        case PlanValidated():
            return "plan_validated", {
                "report": report_payload(event.report),
                "approvable": event.approvable,
            }
        case AwaitingApproval():
            return "awaiting_approval", {
                "session_id": event.session_id,
                "item_count": event.item_count,
            }
        case ApprovalRecorded():
            return "approval_recorded", {
                "session_id": event.session_id,
                "approved": event.approved,
                "note": event.note,
            }
        case CreationReported():
            return "creation_reported", {
                "items": [
                    {"ref": i.ref, "backend_id": i.backend_id, "url": i.url}
                    for i in event.items
                ]
            }
        case TurnEnded():
            return "turn_ended", {"has_proposal": event.has_proposal}
        case RunFailed():
            return "run_failed", {"reason": event.reason, "retryable": event.retryable}
        case Notice():
            return "notice", {"message": event.message, "level": event.level}
        case _:
            # Unknown event types are reported rather than dropped. A new event
            # the UI does not handle yet is harmless; one that vanished between
            # the use case and the browser is a bug nobody can see.
            return "unknown", {"type": type(event).__name__}


def sse(name: str, payload: dict[str, Any]) -> str:
    """Frame one message as a Server-Sent Event.

    `data` is emitted as a single line: `json.dumps` never emits a raw newline,
    and SSE would read one as the end of the message.
    """
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


def comment(text: str) -> str:
    """An SSE comment line. Used as a keep-alive through idle proxies."""
    return f": {text}\n\n"


# -- domain objects -----------------------------------------------------


def proposal_payload(proposal: PlanProposal) -> dict[str, Any]:
    return {
        "items": [item_payload(item) for item in proposal.items],
        "total_base_hours": _hours(proposal.total_base_hours),
        "total_final_hours": _hours(proposal.total_final_hours),
        "story_hours": {
            story.ref: _hours(proposal.final_hours_of(story.ref))
            for story in proposal.user_stories
        },
    }


def item_payload(item: AnyWorkItem) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ref": item.ref,
        "type": str(item.type),
        "title": item.title,
        "description": item.description,
        "parent_ref": item.parent_ref,
        "sprint": item.sprint.name if item.sprint else None,
        "iteration_path": item.sprint.iteration_path if item.sprint else None,
        "area": item.area,
        "assignee": item.assignee,
        "priority": item.priority,
        "tags": list(item.tags),
    }
    if isinstance(item, Task):
        payload |= {
            "kind": str(item.kind),
            "base_hours": _hours(item.effort.base_hours),
            "final_hours": _hours(item.effort.final_hours),
            "exceeds_maximum": item.effort.exceeds_maximum,
        }
    else:
        payload |= {
            "acceptance_criteria": list(getattr(item, "acceptance_criteria", ())),
            "story_points": getattr(item, "story_points", None),
        }
    return payload


def report_payload(report: ValidationReport) -> dict[str, Any]:
    return {
        "approvable": report.is_approvable,
        "violations": [
            {
                "rule": str(v.rule),
                "severity": str(v.severity),
                "message": v.message,
                "item_ref": v.item_ref,
            }
            for v in report.violations
        ],
    }


def session_payload(session: PlanningSession, *, full: bool = False) -> dict[str, Any]:
    """The session as the UI needs it.

    `full=False` is the listing shape. The proposal is the large part and the
    only part a list view has no use for.
    """
    payload: dict[str, Any] = {
        "id": session.id,
        "status": str(session.status),
        "requirement": session.requirement,
        "scope": str(session.scope),
        "levels": [str(level) for level in session.scope.levels],
        "plans_tasks": session.scope.plans_tasks,
        "buffer_factor": _hours(session.buffer_factor),
        "capacity_hours": _hours(session.capacity_hours),
        "prompt_revision": session.prompt_revision,
        "may_create": session.may_create,
        "failure": session.failure,
        "item_count": len(session.proposal.items) if session.proposal else 0,
    }
    if not full:
        return payload
    return payload | {
        "proposal": proposal_payload(session.proposal) if session.proposal else None,
        "report": report_payload(session.report) if session.report else None,
        "decision": (
            {
                "approved": session.decision.approved,
                "note": session.decision.note,
                "decided_at": session.decision.decided_at.isoformat(),
            }
            if session.decision
            else None
        ),
        "created": [
            {"ref": i.ref, "backend_id": i.backend_id, "url": i.url}
            for i in session.created
        ],
    }


def _hours(value: Decimal | None) -> str | None:
    return None if value is None else format_hours(value)
