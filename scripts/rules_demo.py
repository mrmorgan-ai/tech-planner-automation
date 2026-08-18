"""Run the planning rules against a knowingly bad plan and show what they catch.

Not a test — it asserts one thing only, that a plan breaking mandatory rules is
not approvable. Its real job is to make the rules legible: run it and you can
read exactly what the tool refuses to let through, without spending a model call
or waiting on a board.

Run via `make rules`.
"""

from __future__ import annotations

from tech_planner.domain.model.effort import TaskEffort
from tech_planner.domain.model.plan_proposal import PlanProposal
from tech_planner.domain.model.work_item import Task, TaskKind, UserStory
from tech_planner.domain.model.scope import PlanningCadence, PlanningScope
from tech_planner.domain.rules.planning_rules import validate

# One story, two tasks. The first is well over the two-day ceiling; together
# they are far over a sprint's capacity; the Definition of Done is barely
# touched; and there are no acceptance criteria. Every mandatory rule should
# have something to say about this.
BAD_PLAN = PlanProposal(
    items=(
        UserStory(ref="US-1", title="Do everything at once"),
        Task(
            ref="T-1",
            title="Rewrite the payments module",
            parent_ref="US-1",
            effort=TaskEffort.of_hours(30),
            kind=TaskKind.IMPLEMENTATION,
        ),
        Task(
            ref="T-2",
            title="Write it all up afterwards",
            parent_ref="US-1",
            effort=TaskEffort.of_hours(40),
            kind=TaskKind.DOCUMENTATION,
        ),
    )
)


def main() -> int:
    # Rules are scoped: a sprint plan is judged on hours, an annual plan on
    # points. Showing both is the point — the same engine, different questions.
    for cadence in PlanningCadence:
        scope = PlanningScope.for_cadence(cadence)
        print(
            f"scope        {cadence:<10} {scope}  "
            f"{'hours + buffer' if scope.plans_tasks else 'story points'}"
        )

    report = validate(BAD_PLAN)
    print(
        f"rules        {len(report.violations)} findings on a knowingly bad plan, "
        f"approvable={report.is_approvable}"
    )
    for violation in report.violations:
        print(f"             {violation}")

    if report.is_approvable:
        print("\nFAIL  a plan breaking mandatory rules was approvable")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
