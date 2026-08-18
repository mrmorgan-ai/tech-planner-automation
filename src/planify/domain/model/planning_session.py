"""The aggregate root for one planning conversation, and its lifecycle.

The spec's most consequential rule is procedural: **confirm with the user before
creating items**. That is enforced here rather than in a controller, because
"the plan may be written to the backend" is a fact about the session's state,
not about which UI is driving it. The CLI and the HTTP adapter both go through
these transitions, so neither can invent a shortcut past the gate.

The two-pass agent design mirrors this exactly: pass 1 physically cannot create
(the mutating tools are denied), and pass 2 is only ever built for a session
whose `may_create` is true. Belt (permissions) and braces (state).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from planify.domain.errors import DomainError, InvalidTransition
from planify.domain.model.approval import ApprovalDecision, CreatedItem
from planify.domain.model.estimate import DEFAULT_BUFFER_FACTOR
from planify.domain.model.plan_proposal import PlanProposal
from planify.domain.model.scope import DEFAULT_SCOPE, PlanningScope
from planify.domain.rules.violations import ValidationReport


class SessionStatus(StrEnum):
    #: Started; the agent has not returned a proposal yet.
    DRAFTING = "drafting"
    #: A proposal is on the table, awaiting the user's decision.
    PROPOSED = "proposed"
    #: The user declined. A new proposal may still follow.
    REJECTED = "rejected"
    #: The user approved and the rules passed. Pass 2 may run.
    APPROVED = "approved"
    #: Pass 2 is in flight.
    CREATING = "creating"
    #: Items exist in the backend. Terminal.
    CREATED = "created"
    #: Something went wrong. Terminal.
    FAILED = "failed"


#: Statuses from which a fresh proposal may arrive. Notably *not* CREATED:
#: once items exist, re-proposing into the same session would silently
#: disconnect the plan from what was actually written.
_ACCEPTS_PROPOSAL = frozenset(
    {SessionStatus.DRAFTING, SessionStatus.PROPOSED, SessionStatus.REJECTED}
)


@dataclass(slots=True)
class PlanningSession:
    """One requirement, tracked from statement to created work items.

    Mutable by design — it is the one thing in the domain that has a life
    cycle. Everything it holds is immutable.
    """

    #: Also the agent runtime's session id: we assign it rather than parsing it
    #: back out of the event stream, so resuming never depends on the stream.
    id: str = field(default_factory=lambda: str(uuid4()))
    requirement: str = ""
    #: Identifies the system prompt text this session is running under, so an
    #: edit mid-session is visible rather than silent.
    prompt_revision: str | None = None
    #: The planning cadence's level window. Decides which rules applied.
    scope: PlanningScope = field(default=DEFAULT_SCOPE)
    #: The estimate settings this plan was built with, recorded rather than
    #: looked up. Propose on Monday at 1.30, lower the team default to 1.20 on
    #: Tuesday, approve on Wednesday — the board must receive the numbers that
    #: were reviewed and approved, not today's.
    buffer_factor: Decimal = DEFAULT_BUFFER_FACTOR
    capacity_hours: Decimal | None = None
    status: SessionStatus = SessionStatus.DRAFTING
    proposal: PlanProposal | None = None
    report: ValidationReport | None = None
    decision: ApprovalDecision | None = None
    created: tuple[CreatedItem, ...] = ()
    failure: str | None = None

    def __post_init__(self) -> None:
        try:
            UUID(self.id)
        except ValueError as exc:
            # The agent runtime requires a UUID here; failing now beats failing
            # inside a subprocess spawn with a less obvious message.
            raise DomainError(f"session id must be a UUID, got {self.id!r}") from exc

    # -- transitions ------------------------------------------------------

    def record_proposal(self, proposal: PlanProposal, report: ValidationReport) -> None:
        """Accept the result of a propose pass."""
        self._require(_ACCEPTS_PROPOSAL, "record a proposal")
        self.proposal = proposal
        self.report = report
        self.decision = None
        self.status = SessionStatus.PROPOSED

    def decide(self, decision: ApprovalDecision) -> None:
        """Record the user's verdict on the current proposal."""
        self._require({SessionStatus.PROPOSED}, "record a decision")
        assert self.report is not None  # guaranteed by the status check
        if decision.approved and not self.report.is_approvable:
            raise InvalidTransition(
                "cannot approve a plan that breaks mandatory planning rules: "
                + "; ".join(v.message for v in self.report.errors)
            )
        self.decision = decision
        self.status = SessionStatus.APPROVED if decision.approved else SessionStatus.REJECTED

    def begin_creation(self) -> None:
        self._require({SessionStatus.APPROVED}, "begin creation")
        self.status = SessionStatus.CREATING

    def record_creation(self, items: tuple[CreatedItem, ...]) -> None:
        self._require({SessionStatus.CREATING}, "record created items")
        if not items:
            raise InvalidTransition("creation reported success but produced no work items")
        self.created = items
        self.status = SessionStatus.CREATED

    def fail(self, reason: str) -> None:
        """Terminal failure. Allowed from anywhere that has not already finished."""
        if self.status is SessionStatus.CREATED:
            raise InvalidTransition("a session that created work items cannot be failed")
        self.failure = reason
        self.status = SessionStatus.FAILED

    # -- questions the adapters ask ---------------------------------------

    @property
    def may_create(self) -> bool:
        """Whether a create pass may be built for this session.

        The pass-2 argv builder — the only code that unlocks the mutating
        backend tools — is gated on exactly this.
        """
        return self.status is SessionStatus.APPROVED

    @property
    def is_terminal(self) -> bool:
        return self.status in {SessionStatus.CREATED, SessionStatus.FAILED}

    def _require(self, allowed: frozenset[SessionStatus] | set[SessionStatus], action: str) -> None:
        if self.status not in allowed:
            expected = ", ".join(sorted(str(s) for s in allowed))
            raise InvalidTransition(
                f"cannot {action} while session {self.id} is {self.status}; "
                f"expected one of: {expected}"
            )
