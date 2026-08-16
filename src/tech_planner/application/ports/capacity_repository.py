"""Per-sprint capacity, recorded rather than configured.

Sprint capacity is not a property of the team, it is a property of *this*
sprint: two people on holiday, a support rotation, a shortened week. It changes
roughly every two weeks, which is far too often to live in a config file that
has to be edited by hand each time.

So it is stored per sprint name, and resolution runs cheapest-to-most-specific:
an explicit override for this run, then a value recorded for this sprint, then
the configured default.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class CapacityRepository(Protocol):
    def get(self, sprint: str) -> Decimal | None:
        """Recorded capacity for this sprint, or None to fall back."""
        ...

    def set(self, sprint: str, hours: Decimal) -> None: ...

    def clear(self, sprint: str) -> None: ...

    def all(self) -> Mapping[str, Decimal]:
        """Everything recorded, for display."""
        ...


def resolve_capacity(
    repository: CapacityRepository,
    *,
    sprint: str | None,
    override: Decimal | None,
    default: Decimal,
) -> Decimal:
    """Pick the capacity for a run, most specific first."""
    if override is not None:
        return override
    if sprint and (recorded := repository.get(sprint)) is not None:
        return recorded
    return default
