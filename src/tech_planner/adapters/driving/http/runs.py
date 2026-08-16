"""One live agent run per session, and the fan-out of its events.

This is the piece the CLI does not need. There, a run is a `async for` loop
inside the command that started it: it begins when the user presses enter and
ends when the terminal prints the last line. Over HTTP the two are separate —
a POST starts the run and a GET reads it — so something has to own the run in
between. That is this module, and its whole job is lifecycle:

* **Replay.** Events are buffered, so a client that connects after the run
  started, or reconnects after a refresh, sees the run from the beginning
  rather than joining halfway through an assistant message.
* **Fan-out.** Several readers may watch the same run. A slow reader must not
  stall the agent, so each gets its own queue.
* **Reaping.** Every run holds a live `claude` process. A browser tab that goes
  away must not leave one behind, so a run with no readers is cancelled — after
  a grace period, because a page refresh drops the connection for a second and
  losing a plan to that would be absurd.

Cancellation is what actually stops the subprocess: `stream_messages` terminates
it in its `finally`. The generator is closed explicitly via `aclosing` rather
than left to the garbage collector, so the reaping is prompt and observable.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing, suppress
from typing import Any

from tech_planner.application.events import Event, RunFailed
from tech_planner.adapters.driving.http.serialization import event_message

#: How long a run may keep running with nobody watching. Long enough to survive
#: a page refresh or a laptop lid, short enough that an abandoned tab does not
#: leave a runtime burning subscription quota for the rest of the afternoon.
IDLE_GRACE_SECONDS = 90.0

#: Per-subscriber queue depth. Deltas arrive token by token, so this needs
#: headroom; a subscriber that falls this far behind is dropped rather than
#: allowed to hold up the run for everyone else.
_QUEUE_DEPTH = 2048

#: Emitted to every subscriber once the run is over, so an SSE stream can close
#: cleanly instead of being held open by a client waiting for more.
_END = object()

EventSource = Callable[[], AsyncIterator[Event]]


class RunConflict(RuntimeError):
    """A run is already in flight for this session."""


class Run:
    """One agent pass, from the POST that started it to its terminal event."""

    def __init__(self, session_id: str, source: EventSource) -> None:
        self.session_id = session_id
        self._source = source
        self._history: list[tuple[str, dict[str, Any]]] = []
        self._subscribers: set[asyncio.Queue[Any]] = set()
        self._finished = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._reaper: asyncio.Task[None] | None = None

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self._task = asyncio.create_task(self._pump(), name=f"run:{self.session_id}")
        # A run nobody ever reads is on the same clock as one everybody left.
        self._arm_reaper()

    @property
    def running(self) -> bool:
        return not self._finished.is_set()

    async def cancel(self) -> None:
        """Stop the run and, with it, the runtime process behind it."""
        self._disarm_reaper()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._finished.set()

    async def wait(self) -> None:
        await self._finished.wait()

    # -- reading ----------------------------------------------------------

    async def subscribe(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Replay everything so far, then follow the run to its end."""
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=_QUEUE_DEPTH)
        # Snapshot and register in the same step: the pump appends to history
        # and then publishes, so doing this without awaiting in between is what
        # guarantees no event is missed and none is delivered twice.
        backlog = list(self._history)
        self._subscribers.add(queue)
        self._disarm_reaper()
        try:
            for message in backlog:
                yield message
            if not self.running and queue.empty():
                return
            while True:
                message = await queue.get()
                if message is _END:
                    return
                yield message
        finally:
            self._subscribers.discard(queue)
            if not self._subscribers and self.running:
                self._arm_reaper()

    # -- internals --------------------------------------------------------

    async def _pump(self) -> None:
        try:
            async with aclosing(self._source()) as events:
                async for event in events:
                    self._publish(event_message(event))
        except asyncio.CancelledError:
            self._publish(
                event_message(
                    RunFailed(reason="the run was cancelled", retryable=True)
                )
            )
            raise
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            # A use case that raises would otherwise die inside a background
            # task, where the only trace is a warning on the server's console
            # and a browser waiting forever.
            self._publish(event_message(RunFailed(reason=str(exc), retryable=False)))
        finally:
            self._finished.set()
            # Nothing left to reap, so the timer goes too — otherwise a
            # finished run leaves a task sleeping out its grace period.
            self._disarm_reaper()
            for queue in list(self._subscribers):
                _offer(queue, _END)

    def _publish(self, message: tuple[str, dict[str, Any]]) -> None:
        self._history.append(message)
        for queue in list(self._subscribers):
            if not _offer(queue, message):
                # Backed up beyond recovery. Dropping the subscriber keeps the
                # agent running for everyone else; the client can reconnect and
                # replay from history.
                self._subscribers.discard(queue)

    def _arm_reaper(self) -> None:
        if self._reaper is None and self.running:
            self._reaper = asyncio.create_task(self._reap_when_idle())

    def _disarm_reaper(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            self._reaper = None

    async def _reap_when_idle(self) -> None:
        try:
            await asyncio.sleep(IDLE_GRACE_SECONDS)
        except asyncio.CancelledError:
            return
        if not self._subscribers and self.running:
            self._reaper = None
            await self.cancel()


class RunRegistry:
    """Every live run, keyed by session.

    One run per session at a time, deliberately. Two concurrent passes on one
    session would both resume the same agent conversation, and the second would
    be planning against a transcript the first is still writing.
    """

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def start(self, session_id: str, source: EventSource) -> Run:
        existing = self._runs.get(session_id)
        if existing is not None and existing.running:
            raise RunConflict(
                f"session {session_id} already has a run in flight; "
                "wait for it or cancel it first"
            )
        run = Run(session_id, source)
        self._runs[session_id] = run
        run.start()
        return run

    def get(self, session_id: str) -> Run | None:
        return self._runs.get(session_id)

    def active(self) -> tuple[str, ...]:
        return tuple(sid for sid, run in self._runs.items() if run.running)

    async def cancel(self, session_id: str) -> bool:
        run = self._runs.get(session_id)
        if run is None or not run.running:
            return False
        await run.cancel()
        return True

    async def shutdown(self) -> None:
        """Reap everything on the way out.

        Without this, stopping the server would orphan a `claude` process per
        live session — they are children of this process, not of the request
        that started them.
        """
        for run in list(self._runs.values()):
            if run.running:
                await run.cancel()
        self._runs.clear()


def _offer(queue: asyncio.Queue[Any], message: Any) -> bool:
    """Non-blocking put. False when the subscriber is hopelessly behind."""
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:
        return False
    return True
