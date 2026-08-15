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
from pathlib import Path
from typing import Protocol, runtime_checkable

from tech_planner.application.events import Event, PassKind


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


@runtime_checkable
class AgentGateway(Protocol):
    """Runs one pass and streams what happens.

    Implementations yield :class:`~tech_planner.application.events.Event`s and
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

    async def preflight(self) -> tuple[str, ...]:
        """Check the runtime is usable and report what it can reach.

        Returns the names of the MCP servers that connected. Raises if the
        runtime is missing, unauthenticated, or cannot reach the configured
        backend — `doctor` and session start both go through this so a broken
        environment surfaces before a plan is built on top of it.
        """
        ...
