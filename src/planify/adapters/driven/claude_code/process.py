"""Spawning the runtime and reading its output.

Small, and fussy in specific places for specific reasons — each one below cost
something to discover.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from decimal import Decimal
from typing import Any

from planify.adapters.driven.claude_code.argv import Launch

#: Stream reader buffer. The default is 64 KiB and a result message carrying a
#: full plan's `structured_output` will exceed it, which surfaces as a
#: `LimitOverrunError` on the *last* and most important line of the run.
_STREAM_LIMIT = 16 * 1024 * 1024

#: Grace period between asking the runtime to stop and killing it. It flushes
#: buffered output on the way out, and cutting that short loses the tail of the
#: stream — including, on a create pass, the record of what was created.
_SHUTDOWN_GRACE_SECONDS = 30.0

#: A process terminated by SIGTERM. Expected during shutdown, not an error.
_SIGTERM_EXIT_CODE = 143


class RuntimeUnavailable(RuntimeError):
    """The agent runtime is missing, or refused to start."""


class RuntimeFailed(RuntimeError):
    """The runtime exited badly. Carries whatever it said on stderr."""


def ensure_runtime(binary: str) -> str:
    """Resolve the runtime on PATH, or explain what to do about it."""
    resolved = shutil.which(binary)
    if resolved is None:
        raise RuntimeUnavailable(
            f"{binary!r} was not found on PATH. This tool drives your own Claude "
            "Code installation rather than calling an API, so the CLI must be "
            "installed and signed in."
        )
    return resolved


async def stream_messages(launch: Launch) -> AsyncIterator[Mapping[str, Any]]:
    """Run one pass, yielding each decoded stdout message.

    Cancelling the consumer terminates the subprocess: every planning session
    holds a live process, so an abandoned stream must not leave one behind.
    """
    ensure_runtime(launch.argv[0])
    launch.cwd.mkdir(parents=True, exist_ok=True)

    process = await asyncio.create_subprocess_exec(
        *launch.argv,
        cwd=str(launch.cwd),
        env=dict(launch.env),
        # Closed rather than left open: with print mode the runtime waits a few
        # seconds for piped stdin before giving up and warning about it.
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=_STREAM_LIMIT,
    )
    assert process.stdout is not None and process.stderr is not None

    errors = asyncio.ensure_future(_drain(process.stderr))
    try:
        async for line in process.stdout:
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                # `parse_float=Decimal` keeps estimate arithmetic exact from the
                # wire inwards. Decoding 6.5 as a binary float and converting
                # later would reintroduce precisely the drift the domain's use
                # of Decimal exists to prevent.
                message = json.loads(text, parse_float=Decimal)
            except json.JSONDecodeError:
                # Not everything on stdout is ours — a wrapper script's banner,
                # for instance. Skip it rather than fail the run.
                continue
            if isinstance(message, Mapping):
                yield message
    finally:
        await _shutdown(process)
        stderr_text = ""
        with suppress(asyncio.CancelledError):
            stderr_text = (await errors).strip()

    code = process.returncode
    if code not in (0, None, _SIGTERM_EXIT_CODE):
        raise RuntimeFailed(
            f"the agent runtime exited with code {code}"
            + (f": {stderr_text}" if stderr_text else "")
        )


class AgentProcess:
    """A runtime kept alive across several turns.

    `stream_messages` above spawns a process, reads one answer and lets it die.
    This does not: the process is started once and fed turns as newline-
    delimited JSON on stdin, which is what `--input-format stream-json` expects.

    Keeping it alive is the entire point. The agent researched the backend's
    iterations and read the code on turn one; a follow-up such as "split that
    story in two" should cost one turn, not a fresh investigation that might
    reach different conclusions than the plan already on screen.

    Verified against the runtime rather than assumed: one process answers turn
    after turn, emitting a `system/init` and a `result` for each, and exits 0
    when stdin closes.
    """

    def __init__(self, launch: Launch) -> None:
        self._launch = launch
        self._process: asyncio.subprocess.Process | None = None
        self._stderr: asyncio.Future[str] | None = None

    async def start(self) -> None:
        ensure_runtime(self._launch.argv[0])
        self._launch.cwd.mkdir(parents=True, exist_ok=True)
        self._process = await asyncio.create_subprocess_exec(
            *self._launch.argv,
            cwd=str(self._launch.cwd),
            env=dict(self._launch.env),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STREAM_LIMIT,
        )
        assert self._process.stderr is not None
        self._stderr = asyncio.ensure_future(_drain(self._process.stderr))

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def send(self, text: str) -> None:
        """Write one user turn."""
        if self._process is None or self._process.stdin is None or not self.alive:
            raise RuntimeFailed("the agent session is no longer running")
        line = json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            },
            separators=(",", ":"),
        )
        self._process.stdin.write((line + "\n").encode("utf-8"))
        await self._process.stdin.drain()

    async def messages(self) -> AsyncIterator[Mapping[str, Any]]:
        """Every decoded message, for the life of the conversation."""
        if self._process is None or self._process.stdout is None:
            raise RuntimeFailed("the agent session was never started")
        async for line in self._process.stdout:
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                message = json.loads(text, parse_float=Decimal)
            except json.JSONDecodeError:
                continue
            if isinstance(message, Mapping):
                yield message

    async def close(self) -> None:
        """Close stdin and stop the process.

        Closing stdin first is what makes a clean exit possible: the runtime
        treats it as the end of the conversation and shuts down of its own
        accord. `_shutdown` is the fallback for when it does not.
        """
        if self._process is None:
            return
        if self._process.stdin is not None and not self._process.stdin.is_closing():
            with suppress(BrokenPipeError, ConnectionResetError):
                self._process.stdin.close()
        await _shutdown(self._process)
        if self._stderr is not None:
            self._stderr.cancel()

    async def stderr_text(self) -> str:
        if self._stderr is None:
            return ""
        with suppress(asyncio.CancelledError):
            return (await self._stderr).strip()
        return ""


async def _drain(stream: asyncio.StreamReader) -> str:
    chunks: list[bytes] = []
    with suppress(asyncio.CancelledError, ValueError):
        async for chunk in stream:
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


async def _shutdown(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=_SHUTDOWN_GRACE_SECONDS)
    except TimeoutError:
        process.kill()
        with suppress(ProcessLookupError):
            await process.wait()
