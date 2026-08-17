"""The `AgentGateway` implementation: argv + process + mapper, wired together.

Deliberately thin. Everything with a decision in it lives next door — flags in
`argv`, permissions in `policy`, translation in `stream_mapper`, parsing in
`dto` — so this file stays readable as the sequence it describes.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from tech_planner.adapters.driven.claude_code.argv import build_launch, turn_text
from tech_planner.adapters.driven.claude_code.process import (
    AgentProcess,
    RuntimeFailed,
    RuntimeUnavailable,
    ensure_runtime,
    stream_messages,
)
from tech_planner.adapters.driven.claude_code.stream_mapper import StreamMapper
from tech_planner.adapters.driven.policy.backend_tools import tools_for
from tech_planner.application.events import (
    Event,
    Notice,
    PassKind,
    RunFailed,
    RunStarted,
)
from tech_planner.application.ports.agent_gateway import AgentRequest
from tech_planner.application.ports.settings_provider import SettingsProvider
from tech_planner.application.settings import Settings


class _Preflight:
    """Remembers the last preflight, and lets several callers share one.

    Preflight costs a whole runtime start — around thirty seconds — to learn
    two things that do not change while the server is up: which MCP servers
    connect, and whether the backend's write tools still have the names the
    gate denies. Paying that per session put half a minute of silence in front
    of every plan, before a single line of output.

    So it is answered once. Concurrent callers wait on the same attempt rather
    than starting their own, and a failure is not cached — a backend that was
    down when the server booted must be allowed to come back.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[tuple[str, ...]] | None = None

    async def get(self, probe: Callable[[], Awaitable[tuple[str, ...]]], *, refresh: bool = False):
        if refresh or self._task is None or (self._task.done() and self._task.exception()):
            self._task = asyncio.ensure_future(probe())
        return await asyncio.shield(self._task)


@dataclass(frozen=True, slots=True)
class ClaudeCodeGateway:
    """Drives the user's own Claude Code installation as a subprocess.

    Every run happens on the user's Claude Code subscription. The runtime is
    already signed in, so the tool holds no credential of its own and passes
    none along; `argv.child_env` clears anything that would redirect billing
    elsewhere, which makes that structural rather than aspirational.
    """

    settings: SettingsProvider
    #: Shared, so the thirty-second runtime start it costs is paid once per
    #: process rather than once per planning session.
    _preflight: _Preflight = field(default_factory=_Preflight, repr=False)

    async def run(self, request: AgentRequest) -> AsyncIterator[Event]:
        settings = self.settings.load()
        mapper = StreamMapper(
            request.kind,
            session_id=request.session_id,
            required_servers=_required_servers(settings),
            buffer_factor=request.buffer_factor,
        )

        with _system_prompt_file(request.system_prompt) as prompt_path:
            launch = build_launch(request, settings, system_prompt_path=prompt_path)
            try:
                async for message in stream_messages(launch):
                    for event in mapper.map(message):
                        yield event
                        if isinstance(event, RunFailed):
                            # An unusable environment reported at init: stop
                            # reading rather than let the run continue against
                            # a backend we know it cannot reach.
                            return
            except (RuntimeUnavailable, RuntimeFailed) as exc:
                yield RunFailed(reason=str(exc), retryable=False)
                return

        if not mapper.saw_terminal:
            # The stream ended without a result message. The port promises
            # callers exactly one terminal event, and this is the only place
            # that promise could otherwise be broken.
            yield RunFailed(
                reason="the agent runtime exited without reporting a result",
                retryable=True,
            )

    async def converse(self, request: AgentRequest) -> ClaudeCodeConversation:
        """Open a multi-turn planning session and submit its first turn."""
        if request.kind is not PassKind.PROPOSE:
            # The create pass writes. A process that can take another turn is a
            # process whose scope can still change after approval, so it stays
            # one-shot by construction rather than by convention.
            raise RuntimeFailed("only a propose pass may be run as a conversation")

        settings = self.settings.load()
        conversation = ClaudeCodeConversation(request=request, settings=settings)
        await conversation.open()
        return conversation

    async def preflight(self, *, refresh: bool = False) -> tuple[str, ...]:
        """What the runtime can reach. Answered from cache after the first call."""
        return await self._preflight.get(self._probe, refresh=refresh)

    async def _probe(self) -> tuple[str, ...]:
        """Start a run, read its init message, and stop.

        The init message is emitted before the runtime makes its first model
        request, so this reports the real MCP topology — the user's servers and
        our backend together — for the price of process startup rather than a
        planning turn.
        """
        settings = self.settings.load()
        ensure_runtime(settings.agent.binary)

        # Probed as a CREATE pass on purpose. A propose pass denies the
        # backend's write tools, and a denied tool is not advertised — so
        # probing with one would make every write tool look missing. Nothing
        # can be created here regardless: the stream is abandoned at the init
        # message, before the runtime has taken a single turn.
        request = AgentRequest(
            session_id=str(uuid4()),
            kind=PassKind.CREATE,
            prompt="Reply with the single word: ready.",
            system_prompt="Answer in one word.",
        )
        mapper = StreamMapper(
            request.kind,
            session_id=request.session_id,
            required_servers=_required_servers(settings),
        )

        with _system_prompt_file(request.system_prompt) as prompt_path:
            launch = build_launch(request, settings, system_prompt_path=prompt_path)
            async for message in stream_messages(launch):
                for event in mapper.map(message):
                    if isinstance(event, RunStarted):
                        _verify_gate(settings, event.tools)
                        return event.mcp_servers
                    if isinstance(event, RunFailed):
                        raise RuntimeFailed(event.reason)

        raise RuntimeFailed(
            "the agent runtime started but never reported its configuration"
        )


class ClaudeCodeConversation:
    """One long-lived planning session, and the turns taken in it.

    The system prompt file has to outlive a single turn here, which is the one
    real difference from `run`: the one-shot path writes it, spawns, and
    deletes it inside a `with`, whereas this session may be asked for another
    turn at any point until the user closes it. It is removed in `close`.
    """

    def __init__(self, request: AgentRequest, settings: Settings) -> None:
        self._request = request
        self._settings = settings
        self._prompt = _system_prompt_file(request.system_prompt)
        self._process: AgentProcess | None = None
        #: Set once close has been asked for. A runtime shut down mid-turn
        #: reports `error_during_execution` on its way out, and that must not
        #: be mistaken for a failed plan — the session it belongs to may hold a
        #: perfectly good proposal that the user is about to approve.
        self._closing = False
        self._mapper = StreamMapper(
            request.kind,
            session_id=request.session_id,
            required_servers=_required_servers(settings),
            buffer_factor=request.buffer_factor,
            interactive=True,
        )

    async def open(self) -> None:
        prompt_path = self._prompt.__enter__()
        launch = build_launch(
            self._request,
            self._settings,
            system_prompt_path=prompt_path,
            interactive=True,
        )
        self._process = AgentProcess(launch)
        await self._process.start()
        # The first turn goes in the same way every later one does. Making it a
        # command-line argument instead would mean two code paths that have to
        # stay in agreement about how a turn is phrased.
        await self._process.send(turn_text(self._request))

    async def send(self, text: str) -> None:
        if self._process is None:
            raise RuntimeFailed("the conversation was never opened")
        await self._process.send(text)

    async def events(self) -> AsyncIterator[Event]:
        if self._process is None:
            raise RuntimeFailed("the conversation was never opened")
        # Said immediately, because the runtime takes the better part of a
        # minute to start with a dozen MCP servers to connect, and until its
        # init message arrives there is nothing else to show. An empty panel
        # for thirty seconds reads as broken rather than busy.
        yield Notice(message="Waking up your Claude Code session…")
        try:
            async for message in self._process.messages():
                for event in self._mapper.map(message):
                    if self._closing:
                        # Shutting down on request. Whatever the runtime says on
                        # its way out is an artefact of being stopped, not news.
                        return
                    yield event
                    if isinstance(event, RunFailed):
                        return
        except (RuntimeUnavailable, RuntimeFailed) as exc:
            if self._closing:
                return
            yield RunFailed(reason=str(exc), retryable=False)
            return

        # Reaching here means stdout closed. For a conversation that is the end
        # of the session, and it is only a failure if it happened mid-turn.
        stderr = await self._process.stderr_text()
        if not self._closing and not self._mapper.saw_terminal:
            yield RunFailed(
                reason="the agent session ended without answering"
                + (f": {stderr}" if stderr else ""),
                retryable=True,
            )

    async def close(self) -> None:
        self._closing = True
        if self._process is not None:
            await self._process.close()
        self._prompt.__exit__()


def _verify_gate(settings: Settings, advertised: tuple[str, ...]) -> None:
    """Check the propose-pass deny-list names tools that actually exist.

    This exists because of a real failure, not a hypothetical one. The tool
    names taken from the backend's documentation had all been replaced by the
    time it shipped, and a deny-list of names that no longer exist denies
    nothing at all — while still printing a gate that looks correct.

    Nothing else in the system can catch that. The run succeeds, the plan looks
    fine, and the only symptom is work items appearing during a pass that was
    supposed to be incapable of creating them. So the names are checked against
    what the runtime advertises, once, at startup.
    """
    if settings.backend.mcp_config is None or not advertised:
        return

    backend = tools_for(settings.backend.name)
    available = set(advertised)
    missing = [name for name in backend.qualified_mutating if name not in available]
    if not missing:
        return

    raise RuntimeFailed(
        "the backend's write tools are not what this adapter expects, so the "
        "planning gate would not actually block anything.\n"
        "  missing:   " + ", ".join(missing) + "\n"
        "  available: "
        + ", ".join(sorted(t for t in available if t.startswith(f"mcp__{backend.server}__")))
        + "\nUpdate BackendTools in adapters/driven/policy/backend_tools.py to match."
    )


def _required_servers(settings: Settings) -> tuple[str, ...]:
    """The MCP servers whose absence should stop a run.

    Only the work-tracking backend, and only when one is actually configured.
    Every other server in the user's environment is a capability we are glad to
    have and can plan without.
    """
    if settings.backend.mcp_config is None:
        return ()
    return (tools_for(settings.backend.name).server,)


class _system_prompt_file:
    """Write the assembled prompt somewhere the runtime can read it.

    A file rather than an argument: the prompt carries the full planning rules
    and adapter mapping, and putting that on a command line is both fragile and
    unpleasant to read in a process listing.
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self._path: Path | None = None

    def __enter__(self) -> Path:
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", prefix="tech-planner-prompt-", delete=False, encoding="utf-8"
        )
        with handle:
            handle.write(self._text)
        self._path = Path(handle.name)
        return self._path

    def __exit__(self, *_: object) -> None:
        if self._path is not None:
            self._path.unlink(missing_ok=True)
