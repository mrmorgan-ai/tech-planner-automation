"""Findings produced by validating a proposal.

A violation is *not* an exception. The user is meant to see these, weigh them,
and decide — that is the whole point of proposing before creating. Raising would
throw away a plan that is 95% right over one oversized task.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    #: Breaks a rule the spec states as mandatory. Should block approval.
    ERROR = "error"
    #: Allowed, but the spec expresses a preference against it.
    WARNING = "warning"
    #: Something the user should know; no judgement attached.
    INFO = "info"


class RuleId(StrEnum):
    TASK_EXCEEDS_MAX_DAYS = "task_exceeds_max_days"
    TASK_EXCEEDS_IDEAL_DAYS = "task_exceeds_ideal_days"
    STORY_EXCEEDS_SPRINT_CAPACITY = "story_exceeds_sprint_capacity"
    STORY_HAS_NO_TASKS = "story_has_no_tasks"
    STORY_MISSING_DOD_TASKS = "story_missing_dod_tasks"
    STORY_MISSING_ACCEPTANCE_CRITERIA = "story_missing_acceptance_criteria"
    STORY_MIXES_POINTS_AND_HOURS = "story_mixes_points_and_hours"
    BUFFER_ARITHMETIC_CORRECTED = "buffer_arithmetic_corrected"
    PLAN_HAS_NO_USER_STORIES = "plan_has_no_user_stories"
    #: An item at a level the current planning cadence does not cover — a Task
    #: in an annual plan, say.
    ITEM_OUTSIDE_PLANNING_SCOPE = "item_outside_planning_scope"
    #: Nothing was produced at the level this cadence exists to produce.
    PLAN_EMPTY_AT_BOTTOM_LEVEL = "plan_empty_at_bottom_level"
    #: The sizing level carries no estimate. In cadences above sprint level
    #: that means story points, since there are no hours to give.
    MISSING_STORY_POINTS = "missing_story_points"


@dataclass(frozen=True, slots=True)
class RuleViolation:
    rule: RuleId
    severity: Severity
    message: str
    #: Ref of the work item the finding is about, when it is about one.
    item_ref: str | None = None

    def __str__(self) -> str:
        where = f" [{self.item_ref}]" if self.item_ref else ""
        return f"{self.severity.upper()}{where}: {self.message}"


@dataclass(frozen=True, slots=True)
class ValidationReport:
    violations: tuple[RuleViolation, ...]

    @property
    def errors(self) -> tuple[RuleViolation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[RuleViolation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.WARNING)

    @property
    def is_approvable(self) -> bool:
        """Whether this plan may proceed to creation.

        Warnings do not block: the spec expresses preferences the user is
        entitled to override. Errors do.
        """
        return not self.errors

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return bool(self.violations)
