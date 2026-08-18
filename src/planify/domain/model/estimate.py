"""The estimation buffer rule.

The spec is explicit: ``final_estimate = base_estimate x 1.30``, and both figures
must always be shown. It does *not* settle a rounding policy, so this module
settles one, in one place:

    estimates are quantised to the nearest half hour, rounding half away from zero.

Half-hour granularity keeps task estimates readable (``6.5h -> 8.5h`` rather than
``8.45h``) at a scale where finer precision is false confidence anyway.

Arithmetic uses ``Decimal`` rather than ``float`` deliberately. Binary floats
cannot represent 1.30 exactly, so a float pipeline accumulates drift across the
dozens of tasks in a plan and can make the same base estimate round differently
depending on how it was reached.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from planify.domain.errors import InvalidEstimate

#: Contingency multiplier applied to every base estimate, unless configured
#: otherwise. The spec fixes it at 1.30; teams adjust it as they learn what
#: their own contingency actually costs, so it is a default rather than a law.
DEFAULT_BUFFER_FACTOR: Final[Decimal] = Decimal("1.30")

#: A factor below 1 would shrink estimates, which is not contingency; one much
#: above 2 is not a buffer but a different estimate.
MIN_BUFFER_FACTOR: Final[Decimal] = Decimal("1")
MAX_BUFFER_FACTOR: Final[Decimal] = Decimal("3")

#: Estimates are rounded to a multiple of this many hours.
QUANTUM_HOURS: Final[Decimal] = Decimal("0.5")

#: Guard against a model emitting a nonsense figure (e.g. minutes read as hours).
MAX_REASONABLE_HOURS: Final[Decimal] = Decimal("1000")


def quantize_hours(hours: Decimal) -> Decimal:
    """Round `hours` to the nearest :data:`QUANTUM_HOURS`, half away from zero."""
    steps = (hours / QUANTUM_HOURS).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return steps * QUANTUM_HOURS


@dataclass(frozen=True, slots=True)
class Estimate:
    """A base estimate in hours, and the buffered figure derived from it.

    Only the base is stored. The final figure is *always* computed, never
    accepted from outside — that is the entire point of this type.
    """

    base_hours: Decimal
    #: Stored alongside the base, not read from a global. An estimate has to
    #: stay reproducible: a plan approved at 1.30 must still write 1.30 to the
    #: board after someone changes the team default to 1.20 next week.
    buffer_factor: Decimal = DEFAULT_BUFFER_FACTOR

    def __post_init__(self) -> None:
        if not isinstance(self.base_hours, Decimal):
            raise InvalidEstimate(
                f"base_hours must be a Decimal, got {type(self.base_hours).__name__}"
            )
        if self.base_hours <= 0:
            raise InvalidEstimate(f"base estimate must be positive, got {self.base_hours}")
        if self.base_hours > MAX_REASONABLE_HOURS:
            raise InvalidEstimate(
                f"base estimate of {self.base_hours}h exceeds the sanity ceiling "
                f"of {MAX_REASONABLE_HOURS}h"
            )
        if not MIN_BUFFER_FACTOR <= self.buffer_factor <= MAX_BUFFER_FACTOR:
            raise InvalidEstimate(
                f"buffer factor {self.buffer_factor} is outside the sensible range "
                f"{MIN_BUFFER_FACTOR}-{MAX_BUFFER_FACTOR}"
            )

    @classmethod
    def of(
        cls,
        base_hours: Decimal | int | str,
        buffer_factor: Decimal = DEFAULT_BUFFER_FACTOR,
    ) -> Estimate:
        """Build from anything losslessly convertible to ``Decimal``.

        ``float`` is refused rather than silently coerced: accepting it would
        reintroduce exactly the drift this type exists to avoid.
        """
        if isinstance(base_hours, float):
            raise InvalidEstimate(
                "refusing to build an Estimate from float; pass Decimal, int, or str"
            )
        return cls(Decimal(base_hours), buffer_factor)

    @property
    def final_hours(self) -> Decimal:
        """The buffered estimate: base x the factor, quantised."""
        return quantize_hours(self.base_hours * self.buffer_factor)

    @property
    def buffer_hours(self) -> Decimal:
        """The contingency portion alone — what the buffer actually bought."""
        return self.final_hours - self.base_hours

    def disagrees_with(self, claimed_final: Decimal) -> bool:
        """Whether a model-supplied final figure differs from the computed one.

        The caller decides what to do about it. Our figure always wins; the
        discrepancy is worth reporting because a model that miscalculates the
        buffer has usually miscalculated more than the arithmetic.
        """
        return quantize_hours(claimed_final) != self.final_hours

    def __str__(self) -> str:
        return f"{format_hours(self.base_hours)}h base / {format_hours(self.final_hours)}h final"


def format_hours(value: Decimal) -> str:
    """Render a Decimal without exponent notation or trailing zeros.

    Every hour figure shown to a user goes through here, so ``4`` and ``5.0``
    never turn up side by side in the same sentence.
    """
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        # `normalize` turns Decimal("10") into Decimal("1E+1"); quantizing to a
        # unit exponent is what actually renders it as "10".
        return str(normalized.quantize(Decimal(1)))
    return str(normalized)
