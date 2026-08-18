"""How far up and down the hierarchy a planning session reaches.

Planning happens on a cadence, and each cadence works at a different altitude:
annual planning shapes Epics into Features, quarterly planning breaks Features
into User Stories, sprint planning breaks User Stories into Tasks. Each hands
the next its input, so the levels form a contiguous two-level window rather
than a fixed tree from the top.

This matters far beyond the prompt, because **most of the planning rules only
apply when Tasks are in scope**. The x1.30 buffer, the two-day ceiling, the
Definition of Done and sprint capacity are all statements about hours, and
there are no hours in an annual plan. Treating their absence as a violation
would make every coarse plan unapprovable; treating it as inapplicable is what
lets one rule engine serve all three cadences.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from tech_planner.domain.errors import DomainError
from tech_planner.domain.model.work_item import WorkItemType

#: The hierarchy, coarsest first. Position in this tuple is the level's depth.
LEVEL_ORDER: Final[tuple[WorkItemType, ...]] = (
    WorkItemType.EPIC,
    WorkItemType.FEATURE,
    WorkItemType.USER_STORY,
    WorkItemType.TASK,
)

_DEPTH: Final[dict[WorkItemType, int]] = {
    level: index for index, level in enumerate(LEVEL_ORDER)
}


class PlanningCadence(StrEnum):
    """The planning event a session belongs to."""

    ANNUAL = "annual"
    QUARTERLY = "quarterly"
    SPRINT = "sprint"


_CADENCE_LEVELS: Final[dict[PlanningCadence, tuple[WorkItemType, WorkItemType]]] = {
    PlanningCadence.ANNUAL: (WorkItemType.EPIC, WorkItemType.FEATURE),
    PlanningCadence.QUARTERLY: (WorkItemType.FEATURE, WorkItemType.USER_STORY),
    PlanningCadence.SPRINT: (WorkItemType.USER_STORY, WorkItemType.TASK),
}


@dataclass(frozen=True, slots=True)
class PlanningScope:
    """A contiguous window of the hierarchy: everything from `top` to `bottom`."""

    top: WorkItemType
    bottom: WorkItemType

    def __post_init__(self) -> None:
        if _DEPTH[self.top] > _DEPTH[self.bottom]:
            raise DomainError(
                f"planning scope {self.top}..{self.bottom} is inverted; "
                f"{self.top} is coarser than {self.bottom}"
            )

    @classmethod
    def for_cadence(cls, cadence: PlanningCadence) -> PlanningScope:
        top, bottom = _CADENCE_LEVELS[cadence]
        return cls(top=top, bottom=bottom)

    @classmethod
    def parse(cls, text: str) -> PlanningScope:
        """Build from a cadence name or an explicit ``epic..feature`` range."""
        text = text.strip().lower()
        if ".." not in text:
            try:
                return cls.for_cadence(PlanningCadence(text))
            except ValueError:
                raise DomainError(
                    f"unknown planning cadence {text!r}; expected one of "
                    + ", ".join(str(c) for c in PlanningCadence)
                    + " or a range like 'epic..feature'"
                ) from None
        top, _, bottom = text.partition("..")
        return cls(top=_level(top), bottom=_level(bottom))

    @property
    def levels(self) -> tuple[WorkItemType, ...]:
        return LEVEL_ORDER[_DEPTH[self.top] : _DEPTH[self.bottom] + 1]

    def includes(self, level: WorkItemType) -> bool:
        return level in self.levels

    @property
    def plans_tasks(self) -> bool:
        """Whether hours exist at all in this plan.

        The switch every hour-based rule is gated on.
        """
        return WorkItemType.TASK in self.levels

    @property
    def describable_level(self) -> WorkItemType:
        """The deepest level in scope that carries acceptance criteria.

        Tasks do not, so in a sprint plan this is the User Story above them;
        in coarser plans it is the bottom level itself. This is the level that
        has to say what "done" means, whatever the cadence.
        """
        if self.bottom is not WorkItemType.TASK:
            return self.bottom
        return LEVEL_ORDER[_DEPTH[WorkItemType.TASK] - 1]

    @property
    def sizing_level(self) -> WorkItemType:
        """The level that carries the estimate.

        Tasks carry hours; everything else carries story points. So a sprint
        plan sizes in hours on Tasks, and coarser plans size in points on
        whatever their bottom level happens to be.
        """
        return self.bottom

    def __str__(self) -> str:
        return f"{self.top}..{self.bottom}"


def _level(name: str) -> WorkItemType:
    wanted = name.strip().lower().replace("-", "").replace("_", "")
    for level in LEVEL_ORDER:
        if str(level).lower() == wanted or str(level).lower().replace(" ", "") == wanted:
            return level
    # `userstory` and `story` are both worth accepting; nobody types "UserStory"
    # on a command line twice.
    if wanted in {"story", "us"}:
        return WorkItemType.USER_STORY
    raise DomainError(
        f"unknown planning level {name!r}; expected one of "
        + ", ".join(str(level).lower() for level in LEVEL_ORDER)
    )


#: What sprint planning does, and the default when nothing is configured.
DEFAULT_SCOPE: Final[PlanningScope] = PlanningScope.for_cadence(PlanningCadence.SPRINT)
