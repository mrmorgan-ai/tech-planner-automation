"""The `AgentGateway` implementation: argv + process + mapper, wired together.

Deliberately thin. Everything with a decision in it lives next door — flags in
`argv`, permissions in `policy`, translation in `stream_mapper`, parsing in
`dto` — so this file stays readable as the sequence it describes.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from tech_planner.adapters.driven.claude_code.argv import build_launch
from tech_planner.adapters.driven.claude_code.process import (
    RuntimeFailed,
    RuntimeUnavailable,
    ensure_runtime,
    stream_messages,
)
from tech_planner.adapters.driven.claude_code.stream_mapper import StreamMapper
from tech_planner.adapters.driven.policy.backend_tools import tools_for
from tech_planner.application.events import (
    Event,
    PassKind,
    RunFailed,
    RunStarted,
)
from tech_planner.application.ports.agent_gateway import AgentRequest
from tech_planner.application.ports.settings_provider import SettingsProvider
from tech_planner.application.settings import Settings


@dataclass(frozen=True, slots=True)
class ClaudeCodeGateway:
    """Drives the user's own Claude Code installation as a subprocess.

    Every run happens on the user's Claude Code subscription. The runtime is
    already signed in, so the tool holds no credential of its own and passes
    none along; `argv.child_env` clears anything that would redirect billing
    elsewhere, which makes that structural rather than aspirational.
    """

    settings: SettingsProvider

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

    async def preflight(self) -> tuple[str, ...]:
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
