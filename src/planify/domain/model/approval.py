"""The user's decision on a proposed plan.

Creation in a work-tracking backend is irreversible in practice — nobody wants
to hand-delete forty mis-scoped work items — so the spec makes confirmation
mandatory. This module gives that confirmation a recorded, inspectable shape
rather than leaving it as a boolean somewhere in a controller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """A yes or a no, with the moment and the reasoning attached."""

    approved: bool
    decided_at: datetime = field(default_factory=_now)
    #: Free text from the user. On a rejection this is the useful part: it is
    #: what gets fed back to the agent for the next proposal.
    note: str = ""

    @classmethod
    def approve(cls, note: str = "") -> ApprovalDecision:
        return cls(approved=True, note=note)

    @classmethod
    def reject(cls, note: str = "") -> ApprovalDecision:
        return cls(approved=False, note=note)

    def __str__(self) -> str:
        verdict = "approved" if self.approved else "rejected"
        return f"{verdict}: {self.note}" if self.note else verdict


@dataclass(frozen=True, slots=True)
class CreatedItem:
    """One work item that now exists in the backend.

    `ref` ties it back to the plan-local identifier the proposal used, which is
    what lets us report "US-2 became #4711" rather than a bare list of numbers.
    """

    ref: str
    backend_id: str
    url: str | None = None

    def __str__(self) -> str:
        return f"{self.ref} -> {self.backend_id}"
