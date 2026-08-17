"""Draft-07 schemas for what each pass must return.

Two deliberate shape decisions.

**Flat, not nested.** The plan is a tree, but it is requested as a flat list of
items each naming its `parent_ref`. A deeply nested schema with many required
fields is measurably harder for a model to satisfy, and a failure costs the
whole run. Reassembling the tree and enforcing its invariants is cheap for us
and is `PlanProposal`'s job anyway, so the schema asks for the easy shape and
the domain does the hard part.

**Thin `required` lists.** Only what cannot be defaulted. Every optional field
that is marked required is another way for the run to burn its retries and end
in `error_max_structured_output_retries`.

The schemas are written out by hand rather than generated from model classes.
Generators emit draft 2020-12, the runtime wants draft-07, and the translation
between them is a subtle failure waiting to happen — while these documents are
small enough to read in one screen and are the actual contract with the agent.
"""

from __future__ import annotations

from typing import Any

from tech_planner.domain.model.scope import DEFAULT_SCOPE, PlanningScope

DRAFT_07 = "http://json-schema.org/draft-07/schema#"

_TASK_KINDS = [
    "implementation",
    "technical_testing",
    "functional_testing",
    "deploy_testing",
    "validate_testing",
    "deploy_production",
    "validate_production",
    "documentation",
    "analysis",
    "other",
]

_STRING_LIST: dict[str, Any] = {"type": "array", "items": {"type": "string"}}


def _nullable(*types: str) -> list[str]:
    return [*types, "null"]


def plan_proposal_schema(scope: PlanningScope = DEFAULT_SCOPE) -> dict[str, Any]:
    """What a PROPOSE pass must return, for the cadence being planned.

    The `item_type` enum is narrowed to the levels in scope. Constraining the
    schema is far more effective than asking in prose: an annual plan simply
    cannot come back with Tasks in it.
    """
    return {
        "$schema": DRAFT_07,
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {
            "summary": {
                "type": "string",
                "description": "One paragraph on the approach taken to the breakdown.",
            },
            "items": {
                "type": "array",
                # Zero is allowed on purpose. A schema demanding at least one
                # item forces a plan out of every message, so a greeting or a
                # half-formed idea came back as an invented "capture the
                # requirement" story that the rules then rejected — noise
                # dressed up as work. An empty list is how the agent says "this
                # is not something I can plan yet", and the turn stays a
                # conversation.
                "minItems": 0,
                "description": (
                    "Every work item, flat. Express the hierarchy through "
                    "parent_ref, not by nesting. Return an empty array when the "
                    "message is not yet a plannable requirement — a greeting, a "
                    "question, or a scope too vague to size. Never invent a "
                    "placeholder plan."
                ),
                "items": _work_item_schema(scope),
            },
            "split_rationale": {
                "type": _nullable("string"),
                "description": (
                    "If any User Story was split to fit a single sprint, the "
                    "criterion used for the split."
                ),
            },
            "risks": {
                **_STRING_LIST,
                "description": (
                    "Blockers, external dependencies, missing information, or "
                    "uncertainty that the estimate buffer must not be used to hide."
                ),
            },
        },
    }


def _work_item_schema(scope: PlanningScope) -> dict[str, Any]:
    sizing = scope.sizing_level
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["ref", "item_type", "title"],
        "properties": {
            "ref": {
                "type": "string",
                "description": (
                    "Identifier unique within this plan, used by parent_ref. "
                    "Not a backend id — nothing exists yet."
                ),
            },
            "item_type": {"enum": [str(level) for level in scope.levels]},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "parent_ref": {
                "type": _nullable("string"),
                "description": (
                    "The ref of this item's parent. Epics have none. A Task "
                    "must name the User Story it belongs to."
                ),
            },
            "acceptance_criteria": {
                **_STRING_LIST,
                "description": (
                    "Not for Tasks. One short, testable statement per entry."
                ),
            },
            "story_points": {
                "type": _nullable("integer"),
                "description": (
                    f"Size the {sizing} items in points."
                    if sizing != "Task"
                    else "Not used when Tasks are being planned; size Tasks in hours."
                ),
            },
            "base_estimate_hours": {
                "type": _nullable("number"),
                "description": "Task only. The estimate before any buffer is applied.",
            },
            "final_estimate_hours": {
                "type": _nullable("number"),
                "description": (
                    "Task only. base_estimate_hours multiplied by the buffer factor "
                    "stated in the request. This is recomputed and the computed "
                    "figure is authoritative; it is asked for so that a "
                    "disagreement can be reported."
                ),
            },
            "task_kind": {
                "enum": _TASK_KINDS,
                "description": (
                    "Task only. Definition-of-Done coverage is checked against "
                    "these, so classify honestly."
                ),
            },
            "sprint": {"type": _nullable("string")},
            "iteration_path": {
                "type": _nullable("string"),
                "description": "An iteration path confirmed to exist. Never invent one.",
            },
            "area": {"type": _nullable("string")},
            "assignee": {"type": _nullable("string")},
            "priority": {"type": _nullable("integer")},
            "tags": _STRING_LIST,
        },
    }


def creation_report_schema() -> dict[str, Any]:
    """What a CREATE pass must return."""
    return {
        "$schema": DRAFT_07,
        "type": "object",
        "additionalProperties": False,
        "required": ["created"],
        "properties": {
            "created": {
                "type": "array",
                "description": "One entry per work item actually created.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ref", "backend_id"],
                    "properties": {
                        "ref": {
                            "type": "string",
                            "description": "The plan ref this item was created from.",
                        },
                        "backend_id": {
                            "type": ["string", "integer"],
                            "description": "The identifier the backend assigned.",
                        },
                        "url": {"type": _nullable("string")},
                    },
                },
            },
            "notes": {
                "type": "string",
                "description": (
                    "Anything that did not go to plan — an item that failed, a "
                    "field the backend rejected, a link that could not be made."
                ),
            },
        },
    }
