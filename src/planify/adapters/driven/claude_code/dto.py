"""Turn the agent's structured output into domain objects.

The boundary where untrusted data becomes trusted. Two jobs:

1. Map the flat payload onto `PlanProposal`, letting the domain's invariants
   reject anything malformed.
2. Recompute the estimate buffer, using the factor in force for this run. The
   agent is asked for its own figure, and where
   the two disagree **ours wins** and the disagreement is reported. This is the
   single most concrete reason the domain layer exists: the arithmetic is
   trivial and models still get it wrong somewhere across thirty tasks, quietly.

Written by hand rather than with a validation library. The domain already
rejects everything structurally wrong, so a second schema layer here would
mostly restate it — and the error messages that matter are the ones naming the
offending item's ref, which are easier to write directly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from planify.domain.errors import DomainError
from planify.domain.model.approval import CreatedItem
from planify.domain.model.effort import TaskEffort
from planify.domain.model.estimate import (
    DEFAULT_BUFFER_FACTOR,
    Estimate,
    format_hours,
)
from planify.domain.model.plan_proposal import PlanProposal
from planify.domain.model.sprint import Sprint
from planify.domain.model.work_item import (
    AnyWorkItem,
    Epic,
    Feature,
    Task,
    TaskKind,
    UserStory,
)
from planify.domain.rules.violations import RuleId, RuleViolation, Severity


class MalformedProposal(ValueError):
    """The agent's answer satisfied the schema but does not describe a plan."""


@dataclass(frozen=True, slots=True)
class ParsedProposal:
    proposal: PlanProposal
    #: Corrections made while parsing. Folded into the report the user reviews.
    notes: tuple[RuleViolation, ...] = ()


def parse_proposal(
    payload: Mapping[str, Any],
    *,
    buffer_factor: Decimal = DEFAULT_BUFFER_FACTOR,
) -> ParsedProposal:
    """Map the agent's answer onto the domain, recomputing every estimate.

    The factor is passed in rather than read from a constant, so a plan is
    always buffered with the figure that was in force when it was proposed.
    """
    raw_items = payload.get("items")
    if not isinstance(raw_items, Sequence) or not raw_items:
        raise MalformedProposal("the agent returned no work items")

    items: list[AnyWorkItem] = []
    notes: list[RuleViolation] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, Mapping):
            raise MalformedProposal(f"work item at position {index} is not an object")
        items.append(_build_item(raw, notes, buffer_factor))

    try:
        proposal = PlanProposal(items=tuple(items))
    except DomainError as exc:
        # The hierarchy invariants did their job. Re-raise as a parse failure so
        # the caller can treat it as "the agent answered badly" — which is
        # retryable — rather than as a bug in our own model.
        raise MalformedProposal(str(exc)) from exc

    return ParsedProposal(proposal=proposal, notes=tuple(notes))


def _build_item(
    raw: Mapping[str, Any], notes: list[RuleViolation], buffer_factor: Decimal
) -> AnyWorkItem:
    ref = _text(raw.get("ref"))
    if not ref:
        raise MalformedProposal("a work item has no ref")

    item_type = _text(raw.get("item_type"))
    common: dict[str, Any] = {
        "ref": ref,
        "title": _text(raw.get("title")),
        "description": _text(raw.get("description")),
        "parent_ref": _text(raw.get("parent_ref")) or None,
        "sprint": _sprint(raw),
        "area": _text(raw.get("area")) or None,
        "assignee": _text(raw.get("assignee")) or None,
        "priority": _optional_int(raw.get("priority"), ref, "priority"),
        "tags": _string_tuple(raw.get("tags")),
    }

    try:
        # Every level above Task carries criteria and may carry points: the
        # sizing level moves with the planning cadence.
        described = {
            "acceptance_criteria": _string_tuple(raw.get("acceptance_criteria")),
            "story_points": _optional_int(raw.get("story_points"), ref, "story_points"),
        }
        match item_type:
            case "Epic":
                return Epic(**common, **described)
            case "Feature":
                return Feature(**common, **described)
            case "UserStory":
                return UserStory(**common, **described)
            case "Task":
                return Task(
                    **common,
                    effort=_effort(raw, ref, notes, buffer_factor),
                    kind=_task_kind(raw, ref),
                )
            case _:
                raise MalformedProposal(
                    f"work item {ref!r} has unknown item_type {item_type!r}"
                )
    except DomainError as exc:
        raise MalformedProposal(f"work item {ref!r} is invalid: {exc}") from exc


def _effort(
    raw: Mapping[str, Any],
    ref: str,
    notes: list[RuleViolation],
    buffer_factor: Decimal,
) -> TaskEffort:
    base = _decimal(raw.get("base_estimate_hours"))
    if base is None:
        raise MalformedProposal(
            f"task {ref!r} has no base_estimate_hours; every task must be estimated"
        )

    estimate = Estimate(base, buffer_factor)
    claimed = _decimal(raw.get("final_estimate_hours"))
    if claimed is not None and estimate.disagrees_with(claimed):
        notes.append(
            RuleViolation(
                rule=RuleId.BUFFER_ARITHMETIC_CORRECTED,
                severity=Severity.WARNING,
                item_ref=ref,
                message=(
                    f"agent gave {format_hours(claimed)}h as the buffered estimate; "
                    f"{format_hours(base)}h x {format_hours(buffer_factor)} is "
                    f"{format_hours(estimate.final_hours)}h. "
                    "Using the computed figure."
                ),
            )
        )
    return TaskEffort(estimate)


def _task_kind(raw: Mapping[str, Any], ref: str) -> TaskKind:
    value = _text(raw.get("task_kind"))
    if not value:
        return TaskKind.OTHER
    try:
        return TaskKind(value)
    except ValueError:
        # Not fatal: an unrecognised kind costs Definition-of-Done coverage for
        # that task, which the rules will report, and that is a better outcome
        # than discarding an otherwise sound plan.
        return TaskKind.OTHER


def _sprint(raw: Mapping[str, Any]) -> Sprint | None:
    name = _text(raw.get("sprint"))
    path = _text(raw.get("iteration_path"))
    if not name and not path:
        return None
    return Sprint(name=name or path, iteration_path=path or None)


def dump_proposal(proposal: PlanProposal) -> dict[str, Any]:
    """Serialize a proposal back into the same shape the agent produces.

    One wire format, used in both directions. Persisting a session then reuses
    `parse_proposal` to read it back, so there is a single mapping to keep
    correct rather than two that can drift apart.

    Hours are written as strings so a round trip through JSON cannot quietly
    turn an exact `6.5` into a binary float.
    """
    return {"items": [_dump_item(item) for item in proposal.items]}


def _dump_item(item: AnyWorkItem) -> dict[str, Any]:
    data: dict[str, Any] = {
        "ref": item.ref,
        "item_type": str(item.type),
        "title": item.title,
        "description": item.description,
        "parent_ref": item.parent_ref,
        "area": item.area,
        "assignee": item.assignee,
        "priority": item.priority,
        "tags": list(item.tags),
    }
    if item.sprint is not None:
        data["sprint"] = item.sprint.name
        data["iteration_path"] = item.sprint.iteration_path

    if isinstance(item, Task):
        data["base_estimate_hours"] = str(item.effort.base_hours)
        data["final_estimate_hours"] = str(item.effort.final_hours)
        data["task_kind"] = str(item.kind)
    else:
        data["acceptance_criteria"] = list(item.acceptance_criteria)
        data["story_points"] = item.story_points
    return data


def parse_creation_report(payload: Mapping[str, Any]) -> tuple[CreatedItem, ...]:
    raw_created = payload.get("created")
    if not isinstance(raw_created, Sequence):
        raise MalformedProposal("the create pass reported no 'created' list")

    created: list[CreatedItem] = []
    for entry in raw_created:
        if not isinstance(entry, Mapping):
            continue
        ref = _text(entry.get("ref"))
        backend_id = _text(entry.get("backend_id"))
        if not ref or not backend_id:
            continue
        created.append(
            CreatedItem(ref=ref, backend_id=backend_id, url=_text(entry.get("url")) or None)
        )
    return tuple(created)


# -- coercion ------------------------------------------------------------


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(text for item in value if (text := _text(item)))


def _optional_int(value: Any, ref: str, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise MalformedProposal(
            f"work item {ref!r} has a non-numeric {field}: {value!r}"
        ) from None


def _decimal(value: Any) -> Decimal | None:
    """Coerce to Decimal without ever routing through float.

    The stream is decoded with ``parse_float=Decimal``, so a JSON number
    normally arrives here already exact. The float branch exists only for
    payloads that reached us some other way, and goes via ``str`` so it
    recovers the decimal that was actually written rather than its binary
    approximation.
    """
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, float):
            return Decimal(str(value))
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
