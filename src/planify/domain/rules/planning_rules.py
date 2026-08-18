"""Validate a proposal against the spec's mandatory planning rules.

This is the domain service the whole architecture exists to make possible: with
the plan arriving as data rather than prose, "every task is at most two days"
stops being a request in a prompt and becomes something we check.

**Rules are scoped, not universal.** The x1.30 buffer, the two-day ceiling, the
Definition of Done and sprint capacity are all statements about hours, and an
annual plan has none — it stops at Features. Applying them anyway would make
every coarse plan unapprovable for failing to contain things it was never asked
to contain. So each rule states the level it belongs to, and simply does not run
outside it. What replaces them above sprint level is thinner on purpose: at that
altitude the honest checks are that the right levels are present, that they are
sized in points, and that they say what "done" means.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from planify.domain.model.effort import HOURS_PER_DAY, MAX_DAYS
from planify.domain.model.estimate import format_hours
from planify.domain.model.plan_proposal import PlanProposal
from planify.domain.model.scope import DEFAULT_SCOPE, PlanningScope
from planify.domain.model.sprint import SprintCapacity
from planify.domain.model.work_item import (
    AnyWorkItem,
    Task,
    UserStory,
    WorkItemType,
)
from planify.domain.rules.definition_of_done import DefinitionOfDone
from planify.domain.rules.violations import (
    RuleId,
    RuleViolation,
    Severity,
    ValidationReport,
)


@dataclass(frozen=True, slots=True)
class PlanningPolicy:
    """The team-specific knobs the spec leaves open."""

    #: Which levels this planning session covers. Decides which rules run.
    scope: PlanningScope = field(default=DEFAULT_SCOPE)
    capacity: SprintCapacity = SprintCapacity()
    definition_of_done: DefinitionOfDone = DefinitionOfDone()
    #: Require every sized item to carry acceptance criteria. The spec lists
    #: them as mandatory content, so this defaults on.
    require_acceptance_criteria: bool = True


def validate(proposal: PlanProposal, policy: PlanningPolicy | None = None) -> ValidationReport:
    """Check a proposal and return everything worth telling the user."""
    policy = policy or PlanningPolicy()
    scope = policy.scope
    violations: list[RuleViolation] = []

    violations.extend(_check_scope(proposal, scope))

    if scope.plans_tasks:
        violations.extend(_check_task_sizes(proposal))
        for story in proposal.user_stories:
            violations.extend(_check_story_breakdown(proposal, story, policy))
    else:
        violations.extend(_check_points(proposal, policy))

    violations.extend(_check_acceptance_criteria(proposal, policy))
    return ValidationReport(violations=tuple(violations))


# -- scope ---------------------------------------------------------------


def _check_scope(proposal: PlanProposal, scope: PlanningScope) -> list[RuleViolation]:
    found: list[RuleViolation] = []

    for item in proposal.items:
        if not scope.includes(item.type):
            found.append(
                RuleViolation(
                    rule=RuleId.ITEM_OUTSIDE_PLANNING_SCOPE,
                    severity=Severity.ERROR,
                    item_ref=item.ref,
                    message=(
                        f"{item.type} is outside this plan's scope ({scope}); "
                        "that level belongs to a different planning cadence"
                    ),
                )
            )

    if not proposal.of_type(scope.bottom):
        found.append(
            RuleViolation(
                rule=RuleId.PLAN_EMPTY_AT_BOTTOM_LEVEL,
                severity=Severity.ERROR,
                message=(
                    f"the plan contains no {scope.bottom} items; producing them "
                    f"is the point of a {scope} plan"
                ),
            )
        )
    return found


# -- hours: sprint-level cadences only ------------------------------------


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


def _check_story_breakdown(
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
    missing = dod.missing_from(frozenset(t.kind for t in tasks))
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


# -- points: cadences above sprint level ----------------------------------


def _check_points(proposal: PlanProposal, policy: PlanningPolicy) -> list[RuleViolation]:
    """Above sprint level there are no hours, so sizing is in story points.

    A warning rather than an error: an unsized Feature in an annual plan is
    worth flagging, but it is not the kind of mistake that should stop a year's
    planning from being recorded.
    """
    return [
        RuleViolation(
            rule=RuleId.MISSING_STORY_POINTS,
            severity=Severity.WARNING,
            item_ref=item.ref,
            message=(
                f"{item.type} has no story points; at this planning level "
                "points are the only sizing available"
            ),
        )
        for item in proposal.of_type(policy.scope.sizing_level)
        if getattr(item, "story_points", None) is None
    ]


# -- applies at every level ------------------------------------------------


def _check_acceptance_criteria(
    proposal: PlanProposal, policy: PlanningPolicy
) -> list[RuleViolation]:
    if not policy.require_acceptance_criteria:
        return []
    return [
        RuleViolation(
            rule=RuleId.STORY_MISSING_ACCEPTANCE_CRITERIA,
            severity=Severity.ERROR,
            item_ref=item.ref,
            message=f"{item.type} has no acceptance criteria",
        )
        for item in proposal.items
        if _needs_criteria(item, policy.scope)
        and not getattr(item, "acceptance_criteria", ())
    ]


def _needs_criteria(item: AnyWorkItem, scope: PlanningScope) -> bool:
    """Only the deepest describable level in scope must state its criteria.

    In a sprint plan that is the User Story, not the Task beneath it. In a
    quarterly plan it is the User Story again, not the Feature above it: the
    Feature is context for the stories, and demanding criteria on both produces
    duplication rather than clarity.
    """
    return item.type is scope.describable_level


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
