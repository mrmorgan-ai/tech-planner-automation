"""The port that matters: the agent runtime.

The spec defines an adapter contract for work-tracking backends
(`create_item`, `link_parent`, `resolve_iteration`). That contract is real, but
it is **not** a Python interface here, because we never call the backend — the
model does, through MCP, inside the subprocess. Its adapter is a prompt file.

What this codebase actually adapts is the agent runtime, and that is where the
hexagon earns its keep: the runtime's flag surface and stdout schema are our
most volatile dependency, and writes to a work-tracking backend are effectively
irreversible. Confining both behind this port means the entire two-pass flow is
exercisable against recorded fixtures, with no subprocess and no live board.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol, runtime_checkable

from planify.application.events import Event, PassKind
from planify.domain.model.estimate import DEFAULT_BUFFER_FACTOR
from planify.domain.model.scope import DEFAULT_SCOPE, PlanningScope


@dataclass(frozen=True, slots=True)
class AgentRequest:
    """Everything a pass needs, stated in the application's own terms.

    Note what is *absent*: no tool lists, no flags, no model string, no working
    directory. Those are the adapter's business. A use case says "propose",
    never "propose with --disallowedTools=..." — otherwise the runtime's
    command line would leak into the core, which is the leak this port exists
    to prevent.
    """

    session_id: str
    kind: PassKind
    #: The user turn: the requirement for a PROPOSE pass, the instruction to
    #: write the approved plan for a CREATE pass.
    prompt: str
    #: The complete instruction set for the run. It *replaces* the runtime's
    #: default system prompt rather than adding to it — the prompt the user
    #: edits is the whole of what the model is told.
    system_prompt: str
    #: Attached context documents, passed as part of the turn.
    context_files: Sequence[Path] = ()
    #: Continue an existing runtime session rather than starting one. Always
    #: true for CREATE, so the agent still has the proposal it just made.
    resume: bool = False
    #: Which levels this run plans. Decides the output schema the agent must
    #: satisfy and what it is told to produce.
    scope: PlanningScope = DEFAULT_SCOPE
    #: The contingency multiplier in force for this run. Travels with the
    #: request so a plan is always buffered with the figure it was proposed
    #: under, even if the team default changes before it is approved.
    buffer_factor: Decimal = DEFAULT_BUFFER_FACTOR
    #: Buffered hours one User Story may carry and still fit a sprint.
    #:
    #: Sent to the agent, not just used to judge it afterwards. Without it the
    #: agent is told stories must fit a sprint but not what a sprint holds, so
    #: it produces hundred-hour stories in good faith and only finds out they
    #: are unapprovable after several minutes of work. Telling it the number is
    #: how the rules stop being a surprise.
    capacity_hours: Decimal | None = None


@runtime_checkable
class Conversation(Protocol):
    """A live agent session that accepts more than one turn.

    The one-shot `run` is a question and an answer. This is a conversation: the
    process stays alive between turns, so the agent keeps everything it learned
    — the iterations it queried, the code it read — and a follow-up like "split
    that story" costs one turn instead of a whole new investigation.

    It exists alongside `run` rather than replacing it because the approval gate
    depends on the difference. A conversation runs under one set of tool
    permissions for its whole life; permissions cannot be changed mid-process.
    So planning is a conversation, and creating is a separate pass, launched
    with the backend's write tools unlocked only once a plan has been approved.
    """

    async def send(self, text: str) -> None:
        """Submit a turn. Its events arrive on :meth:`events`."""
        ...

    def events(self) -> AsyncIterator[Event]:
        """Every event for the whole conversation, turn after turn.

        Each turn ends with `TurnEnded`, or with `RunFailed` if the session is
        over. The iterator ends when the conversation closes.
        """
        ...

    async def close(self) -> None:
        """End the conversation and stop the runtime behind it."""
        ...


@runtime_checkable
class AgentGateway(Protocol):
    """Runs one pass and streams what happens.

    Implementations yield :class:`~planify.application.events.Event`s and
    **must** finish with exactly one terminal event: `ProposalReady`,
    `CreationReported`, or `RunFailed`. Callers rely on that guarantee — a
    stream that just stops is treated as a failure, because "the agent said
    nothing" and "the agent succeeded" must never look alike.

    Returning domain objects rather than raw payloads is deliberate: parsing
    and validating the runtime's structured output belongs to the adapter, so
    a fake gateway is a few lines rather than a schema implementation.
    """

    def run(self, request: AgentRequest) -> AsyncIterator[Event]:
        """Execute one pass. The returned stream is single-use."""
        ...

    async def converse(self, request: AgentRequest) -> Conversation:
        """Open a multi-turn session for the request's first turn.

        Only ever used for PROPOSE. A CREATE pass is deliberately one-shot:
        it is the pass that writes, and a process that can take another turn is
        a process whose scope can still change after it was approved.
        """
        ...

    async def preflight(self) -> tuple[str, ...]:
        """Check the runtime is usable and report what it can reach.

        Returns the names of the MCP servers that connected. Raises if the
        runtime is missing, unauthenticated, or cannot reach the configured
        backend — `doctor` and session start both go through this so a broken
        environment surfaces before a plan is built on top of it.
        """
        ...
