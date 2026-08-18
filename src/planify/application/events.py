"""The normalized event vocabulary the application emits.

Everything that happens during a planning session — agent output, tool calls,
rule findings, created items — reaches the outside world as one of these. Both
driving adapters consume the same stream: the CLI prints it, the HTTP adapter
serializes it to SSE.

Deliberately *not* the agent runtime's own event shapes. Claude Code's stdout
schema is our single most volatile dependency, and translating it once, in one
adapter, is the main thing the hexagon buys us. If the CLI renames a field, the
change stops at `stream_mapper.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from planify.domain.model.approval import CreatedItem
from planify.domain.model.plan_proposal import PlanProposal
from planify.domain.rules.violations import RuleViolation, ValidationReport


class Event:
    """Marker base. Consumers should match on concrete types."""


class PassKind(StrEnum):
    """Which of the two passes an agent run is.

    This is the load-bearing distinction in the whole design: PROPOSE runs with
    the backend's mutating tools denied, CREATE runs with them permitted, and
    nothing may go straight to CREATE.
    """

    PROPOSE = "propose"
    CREATE = "create"


# -- agent runtime ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunStarted(Event):
    session_id: str
    kind: PassKind
    model: str | None = None
    #: Which MCP servers actually connected. Reported because a misconfigured
    #: server is skipped silently by the runtime, and planning against a
    #: backend we cannot reach is worse than failing.
    mcp_servers: tuple[str, ...] = ()
    #: Every tool the runtime advertises for this run. Carried so the gate can
    #: be checked against reality: a deny-list naming tools that do not exist
    #: denies nothing, and looks identical to one that works.
    tools: tuple[str, ...] = ()
    resumed: bool = False


@dataclass(frozen=True, slots=True)
class AssistantDelta(Event):
    """A token-level fragment. Emitted only when partial streaming is on."""

    text: str


@dataclass(frozen=True, slots=True)
class AssistantMessage(Event):
    """A complete assistant turn."""

    text: str


@dataclass(frozen=True, slots=True)
class ToolStarted(Event):
    name: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ToolFinished(Event):
    name: str
    ok: bool = True
    detail: str = ""


@dataclass(frozen=True, slots=True)
class AgentRetrying(Event):
    """The runtime is backing off — rate limits or overload.

    Surfaced rather than swallowed: on a subscription this is the signal that
    matters, and without it a long backoff is indistinguishable from a hang.
    """

    reason: str
    attempt: int = 1


# -- terminal outcomes --------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProposalReady(Event):
    """Terminal event of a PROPOSE pass."""

    proposal: PlanProposal
    #: Findings raised while parsing the agent's answer rather than while
    #: checking the plan — chiefly buffer arithmetic we recomputed and
    #: overrode. They belong in the same report the user reviews, so the
    #: use case folds them in rather than reporting them separately.
    notes: tuple[RuleViolation, ...] = ()


@dataclass(frozen=True, slots=True)
class CreationReported(Event):
    """Terminal event of a CREATE pass."""

    items: tuple[CreatedItem, ...]


@dataclass(frozen=True, slots=True)
class TurnEnded(Event):
    """One turn of an interactive conversation finished; the session lives on.

    The one-shot passes have a terminal event and then silence. A conversation
    does not: the agent may answer a question, ask one back, or revise a plan,
    and each of those ends a turn without ending anything else. This is what
    tells the UI it may accept typing again.

    `has_proposal` is false for a turn that was genuinely conversational. That
    is not a failure — in a one-shot pass a result carrying no plan means the
    run produced nothing, but in a conversation it means the agent replied with
    words, which is a thing it is allowed to do.
    """

    has_proposal: bool = False


@dataclass(frozen=True, slots=True)
class RunFailed(Event):
    """Terminal event of a pass that did not produce its expected output."""

    reason: str
    #: Whether retrying the same pass could plausibly succeed. A schema the
    #: agent could not satisfy is retryable; a missing MCP server is not.
    retryable: bool = False


# -- planning workflow ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanValidated(Event):
    """Our rules ran against the agent's proposal. Emitted before any approval.

    This is the concrete payoff of validating in code: the user sees the
    findings *with* the plan, rather than discovering them in the sprint.
    """

    report: ValidationReport
    approvable: bool


@dataclass(frozen=True, slots=True)
class AwaitingApproval(Event):
    """The gate. Nothing is written until a decision comes back."""

    session_id: str
    item_count: int


@dataclass(frozen=True, slots=True)
class ApprovalRecorded(Event):
    session_id: str
    approved: bool
    note: str = ""


@dataclass(frozen=True, slots=True)
class Notice(Event):
    """Something the user should know that is not an agent event."""

    message: str
    level: str = "info"
