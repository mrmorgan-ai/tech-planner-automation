"""Sprint sizing.

The spec fixes the cadence at two weeks and requires that every User Story is
*fully completed* within a single sprint. "Fully completed" means the whole
Definition of Done — implementation, testing, both deployments, validation and
documentation — so capacity is measured against the sum of a story's task
effort, buffered figures included.

Capacity is deliberately configurable rather than derived. A two-week sprint
does not imply 80 hours of story work: it is one person's nominal availability
minus ceremony, support and slack, and only the team knows that number.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from tech_planner.domain.errors import DomainError
from tech_planner.domain.model.effort import HOURS_PER_DAY

#: Spec: sprints are a fixed two weeks.
SPRINT_LENGTH_WEEKS: Final[int] = 2

#: Nominal working days in a two-week sprint.
SPRINT_WORKING_DAYS: Final[Decimal] = Decimal("10")

#: Fallback capacity for one story when the team has not configured a number.
#: Intentionally below the nominal 80h: a story that consumes an entire
#: person-sprint has no room for the validation the DoD demands.
DEFAULT_STORY_CAPACITY_HOURS: Final[Decimal] = SPRINT_WORKING_DAYS * HOURS_PER_DAY * Decimal("0.8")


@dataclass(frozen=True, slots=True)
class Sprint:
    """A target iteration.

    `iteration_path` is the backend's own identifier (for Azure Boards,
    ``Project\\Sprint N``). The domain treats it as an opaque string: resolving
    and validating it is the agent's job, via MCP.
    """

    name: str
    iteration_path: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainError("sprint name must not be blank")


@dataclass(frozen=True, slots=True)
class SprintCapacity:
    """How much buffered work one User Story may carry and still fit a sprint."""

    story_capacity_hours: Decimal = DEFAULT_STORY_CAPACITY_HOURS

    def __post_init__(self) -> None:
        if self.story_capacity_hours <= 0:
            raise DomainError(
                f"story capacity must be positive, got {self.story_capacity_hours}"
            )

    def fits(self, total_final_hours: Decimal) -> bool:
        return total_final_hours <= self.story_capacity_hours
