"""Task sizing: "ideally 1 day, maximum 2".

The spec states the limit in days; Azure Boards stores hours. The conversion
lives here so it is settled once.

The limit is checked against the **buffered** figure, not the base. The buffered
number is what gets committed to the board and what a developer is held to, so
that is the number the 2-day ceiling has to constrain.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from planify.domain.model.estimate import DEFAULT_BUFFER_FACTOR, Estimate

#: Working hours in one day. Azure Boards stores effort in hours.
HOURS_PER_DAY: Final[Decimal] = Decimal("8")

#: Spec: a task should ideally be one day.
IDEAL_DAYS: Final[Decimal] = Decimal("1")

#: Spec: a task must not exceed two days — subdivide instead.
MAX_DAYS: Final[Decimal] = Decimal("2")

IDEAL_HOURS: Final[Decimal] = IDEAL_DAYS * HOURS_PER_DAY
MAX_HOURS: Final[Decimal] = MAX_DAYS * HOURS_PER_DAY


@dataclass(frozen=True, slots=True)
class TaskEffort:
    """The effort attached to a single Task, and the sizing questions about it.

    Note this type does not *reject* oversized tasks. An over-limit task is a
    finding the user should see and act on ("subdivide this"), not a corrupt
    value — so it surfaces through the rules layer rather than by refusing to
    construct. Genuinely impossible values are still rejected, by `Estimate`.
    """

    estimate: Estimate

    @classmethod
    def of_hours(
        cls,
        base_hours: Decimal | int | str,
        buffer_factor: Decimal = DEFAULT_BUFFER_FACTOR,
    ) -> TaskEffort:
        return cls(Estimate.of(base_hours, buffer_factor))

    @property
    def base_hours(self) -> Decimal:
        return self.estimate.base_hours

    @property
    def final_hours(self) -> Decimal:
        return self.estimate.final_hours

    @property
    def final_days(self) -> Decimal:
        return self.final_hours / HOURS_PER_DAY

    @property
    def exceeds_maximum(self) -> bool:
        """Over two days — the spec says subdivide."""
        return self.final_hours > MAX_HOURS

    @property
    def exceeds_ideal(self) -> bool:
        """Over one day but within two — allowed, worth noticing."""
        return self.final_hours > IDEAL_HOURS and not self.exceeds_maximum

    def __str__(self) -> str:
        return str(self.estimate)
