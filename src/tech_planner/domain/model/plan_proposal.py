"""The aggregate root: a proposed breakdown, awaiting approval.

A `PlanProposal` is constructed from the flat item list the agent returns and is
responsible for *structural* correctness — that the thing is a well-formed tree
of the right shape. Construction fails if it is not, because a malformed tree
cannot be meaningfully reviewed or created.

Judgement calls — a task that is too big, a story that will not fit a sprint, a
missing Definition-of-Done task — are **not** enforced here. Those are findings
the user should see and decide about, so they live in `domain.rules` and are
reported rather than raised.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import cached_property

from tech_planner.domain.errors import DuplicateReference, InvalidHierarchy
from tech_planner.domain.model.work_item import (
    ALLOWED_PARENT_TYPES,
    AnyWorkItem,
    Task,
    UserStory,
    WorkItemType,
)


# No `slots=True` here: `cached_property` stores into the instance `__dict__`,
# which slots removes. Frozen is fine — cached_property writes to `__dict__`
# directly rather than going through the blocked `__setattr__`.
@dataclass(frozen=True)
class PlanProposal:
    """A validated tree of work items that has not been created anywhere yet."""

    items: tuple[AnyWorkItem, ...]

    def __post_init__(self) -> None:
        if not self.items:
            raise InvalidHierarchy("a plan proposal must contain at least one work item")
        self._reject_duplicate_refs()
        self._reject_unresolvable_parents()
        self._reject_illegal_nesting()
        self._reject_cycles()

    # -- construction-time invariants ------------------------------------

    def _reject_duplicate_refs(self) -> None:
        seen: set[str] = set()
        for item in self.items:
            if item.ref in seen:
                raise DuplicateReference(f"work item ref {item.ref!r} appears more than once")
            seen.add(item.ref)

    def _reject_unresolvable_parents(self) -> None:
        refs = {item.ref for item in self.items}
        for item in self.items:
            if item.parent_ref is not None and item.parent_ref not in refs:
                raise InvalidHierarchy(
                    f"work item {item.ref!r} names parent {item.parent_ref!r}, "
                    "which is not in the plan"
                )

    def _reject_illegal_nesting(self) -> None:
        by_ref = {item.ref: item for item in self.items}
        for item in self.items:
            parent_type = (
                by_ref[item.parent_ref].type if item.parent_ref is not None else None
            )
            allowed = ALLOWED_PARENT_TYPES[item.type]
            if parent_type not in allowed:
                readable = ", ".join(sorted(str(t) for t in allowed if t is not None)) or "nothing"
                raise InvalidHierarchy(
                    f"{item.type} {item.ref!r} hangs from {parent_type or 'no parent'}; "
                    f"a {item.type} may only hang from: {readable}"
                    + (" (or be a root)" if None in allowed else "")
                )

    def _reject_cycles(self) -> None:
        by_ref = {item.ref: item for item in self.items}
        for item in self.items:
            seen: set[str] = set()
            cursor = item
            while cursor.parent_ref is not None:
                if cursor.ref in seen:
                    raise InvalidHierarchy(
                        f"parentage cycle detected involving work item {item.ref!r}"
                    )
                seen.add(cursor.ref)
                cursor = by_ref[cursor.parent_ref]

    # -- reading the tree -------------------------------------------------

    @cached_property
    def _by_ref(self) -> dict[str, AnyWorkItem]:
        return {item.ref: item for item in self.items}

    def get(self, ref: str) -> AnyWorkItem:
        return self._by_ref[ref]

    def roots(self) -> tuple[AnyWorkItem, ...]:
        return tuple(item for item in self.items if item.parent_ref is None)

    def children_of(self, ref: str) -> tuple[AnyWorkItem, ...]:
        return tuple(item for item in self.items if item.parent_ref == ref)

    def of_type(self, item_type: WorkItemType) -> tuple[AnyWorkItem, ...]:
        return tuple(item for item in self.items if item.type is item_type)

    @property
    def user_stories(self) -> tuple[UserStory, ...]:
        return tuple(i for i in self.items if isinstance(i, UserStory))

    @property
    def tasks(self) -> tuple[Task, ...]:
        return tuple(i for i in self.items if isinstance(i, Task))

    def tasks_of(self, story_ref: str) -> tuple[Task, ...]:
        return tuple(i for i in self.items if isinstance(i, Task) and i.parent_ref == story_ref)

    # -- roll-ups ---------------------------------------------------------

    def base_hours_of(self, story_ref: str) -> Decimal:
        return sum(
            (t.effort.base_hours for t in self.tasks_of(story_ref)), start=Decimal("0")
        )

    def final_hours_of(self, story_ref: str) -> Decimal:
        """Buffered hours for a story — the figure the sprint-fit rule uses."""
        return sum(
            (t.effort.final_hours for t in self.tasks_of(story_ref)), start=Decimal("0")
        )

    @property
    def total_base_hours(self) -> Decimal:
        return sum((t.effort.base_hours for t in self.tasks), start=Decimal("0"))

    @property
    def total_final_hours(self) -> Decimal:
        return sum((t.effort.final_hours for t in self.tasks), start=Decimal("0"))
