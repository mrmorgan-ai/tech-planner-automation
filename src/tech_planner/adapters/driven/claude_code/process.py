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

from tech_planner.adapters.driven.claude_code.argv import Launch

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
