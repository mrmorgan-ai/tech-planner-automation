"""Validate a proposal against the spec's mandatory planning rules.

This is the domain service the whole architecture exists to make possible: with
the plan arriving as data rather than prose, "every task is at most two days"
stops being a request in a prompt and becomes something we check.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from tech_planner.domain.model.effort import HOURS_PER_DAY, MAX_DAYS
from tech_planner.domain.model.estimate import format_hours
from tech_planner.domain.model.plan_proposal import PlanProposal
from tech_planner.domain.model.sprint import SprintCapacity
from tech_planner.domain.model.work_item import TaskKind, UserStory
from tech_planner.domain.rules.definition_of_done import DefinitionOfDone
from tech_planner.domain.rules.violations import (
    RuleId,
    RuleViolation,
    Severity,
    ValidationReport,
)


@dataclass(frozen=True, slots=True)
class PlanningPolicy:
    """The team-specific knobs the spec leaves open."""

    capacity: SprintCapacity = SprintCapacity()
    definition_of_done: DefinitionOfDone = DefinitionOfDone()
    #: Require every story to carry acceptance criteria. The spec lists them as
    #: mandatory story content, so this defaults on.
    require_acceptance_criteria: bool = True


def validate(proposal: PlanProposal, policy: PlanningPolicy | None = None) -> ValidationReport:
    """Check a proposal and return everything worth telling the user."""
    policy = policy or PlanningPolicy()
    violations: list[RuleViolation] = []

    stories = proposal.user_stories
    if not stories:
        violations.append(
            RuleViolation(
                rule=RuleId.PLAN_HAS_NO_USER_STORIES,
                severity=Severity.ERROR,
                message=(
                    "the plan contains no user stories; the tool's purpose is to "
                    "produce user stories broken down as tasks"
                ),
            )
        )

    violations.extend(_check_task_sizes(proposal))
    for story in stories:
        violations.extend(_check_story(proposal, story, policy))

    return ValidationReport(violations=tuple(violations))


def _check_task_sizes(proposal: PlanProposal) -> list[RuleViolation]:
    found: list[RuleViolation] = []
    for task in proposal.tasks:
        if task.effort.exceeds_maximum:
            found.append(
                RuleViolation(
                    rule=RuleId.TASK_EXCEEDS_MAX_DAYS,
                    severity=Severity.ERROR,
                    item_ref=task.ref,
                    message=(
                        f"task is {_days(task.effort.final_hours)} days "
                        f"({format_hours(task.effort.final_hours)}h buffered); "
                        f"the maximum is {_days_from(MAX_DAYS)} — subdivide it"
                    ),
                )
            )
        elif task.effort.exceeds_ideal:
            found.append(
                RuleViolation(
                    rule=RuleId.TASK_EXCEEDS_IDEAL_DAYS,
                    severity=Severity.WARNING,
                    item_ref=task.ref,
                    message=(
                        f"task is {_days(task.effort.final_hours)} days "
                        f"({format_hours(task.effort.final_hours)}h buffered); "
                        "one day is preferred"
                    ),
                )
            )
    return found


def _check_story(
    proposal: PlanProposal, story: UserStory, policy: PlanningPolicy
) -> list[RuleViolation]:
    found: list[RuleViolation] = []
    tasks = proposal.tasks_of(story.ref)

    if not tasks:
        found.append(
            RuleViolation(
                rule=RuleId.STORY_HAS_NO_TASKS,
                severity=Severity.ERROR,
                item_ref=story.ref,
                message="user story has no tasks; it cannot be estimated or executed",
            )
        )
        return found

    total = proposal.final_hours_of(story.ref)
    if not policy.capacity.fits(total):
        found.append(
            RuleViolation(
                rule=RuleId.STORY_EXCEEDS_SPRINT_CAPACITY,
                severity=Severity.ERROR,
                item_ref=story.ref,
                message=(
                    f"story totals {format_hours(total)}h buffered, over the "
                    f"{format_hours(policy.capacity.story_capacity_hours)}h a single "
                    "sprint allows; split it into two or more stories that each "
                    "deliver a verifiable result"
                ),
            )
        )

    dod = policy.definition_of_done.applies_to_tags(story.tags)
    present = frozenset(t.kind for t in tasks)
    missing = dod.missing_from(present)
    if missing:
        found.append(
            RuleViolation(
                rule=RuleId.STORY_MISSING_DOD_TASKS,
                severity=Severity.ERROR,
                item_ref=story.ref,
                message=(
                    "story is missing Definition-of-Done tasks: "
                    + ", ".join(sorted(str(k) for k in missing))
                ),
            )
        )

    if policy.require_acceptance_criteria and not story.acceptance_criteria:
        found.append(
            RuleViolation(
                rule=RuleId.STORY_MISSING_ACCEPTANCE_CRITERIA,
                severity=Severity.ERROR,
                item_ref=story.ref,
                message="story has no acceptance criteria",
            )
        )

    # The spec is firm: points on the story, hours on its tasks, never both on
    # one item. A story carrying its own hours is the shape that breaks it.
    if story.story_points is not None and _has_own_hours(story):
        found.append(
            RuleViolation(
                rule=RuleId.STORY_MIXES_POINTS_AND_HOURS,
                severity=Severity.ERROR,
                item_ref=story.ref,
                message="story carries both story points and an hour estimate",
            )
        )

    return found


def _has_own_hours(story: UserStory) -> bool:
    return getattr(story, "effort", None) is not None


def _days(hours: Decimal) -> str:
    return _days_from(hours / HOURS_PER_DAY)


def _days_from(days: Decimal) -> str:
    """Days, to two places.

    Exact division gives figures like ``1.3125 days``, which reads as precision
    that is not there. The hours beside it are the actionable number.
    """
    return format_hours(days.quantize(Decimal("0.01")))
