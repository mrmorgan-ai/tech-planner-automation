"""The HTTP API: a second driving adapter over the same use cases.

Nothing here decides anything. Starting a session, proposing, validating and
approving are the use cases' business; this file turns requests into calls and
events into Server-Sent Events. The test of that is the approval gate: the
`approve` endpoint cannot create work items, because it does not create work
items — it records a decision on an aggregate that refuses to approve a plan
breaking a mandatory rule, and the create pass is built from that state.

Bound to localhost by the entry point in `main.py`. There is no authentication
because there is no remote: this drives the user's own Claude Code installation
on their own machine, and anything reachable from another host would be driving
their subscription for them.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from tech_planner import composition
from tech_planner.adapters.driven.claude_code.process import (
    RuntimeFailed,
    RuntimeUnavailable,
)
from tech_planner.adapters.driven.filesystem.prompt_repository import (
    unfilled_placeholders,
)
from tech_planner.adapters.driven.policy.tool_policy import permissions_for
from tech_planner.adapters.driving.http.runs import (
    EventSource,
    Run,
    RunConflict,
    RunRegistry,
)
from tech_planner.adapters.driving.http.serialization import (
    comment,
    session_payload,
    sse,
)
from tech_planner.application.events import PassKind
from tech_planner.application.ports.capacity_repository import resolve_capacity
from tech_planner.application.ports.session_repository import SessionNotFound
from tech_planner.application.ports.settings_provider import SettingsError
from tech_planner.application.settings import Settings
from tech_planner.application.use_cases.edit_system_prompt import EmptyPrompt
from tech_planner.application.use_cases.manage_context_files import ContextFileNotFound
from tech_planner.domain.errors import DomainError
from tech_planner.domain.model.approval import ApprovalDecision
from tech_planner.domain.model.planning_session import SessionStatus
from tech_planner.domain.model.scope import PlanningScope

#: Sent on an idle event stream. Proxies and browsers both drop connections
#: that say nothing for long enough, and an agent thinking hard about a large
#: requirement says nothing for a while.
_KEEPALIVE_SECONDS = 15.0


# -- request bodies ------------------------------------------------------


class NewSession(BaseModel):
    """Everything that is stamped on a session when it opens.

    These are recorded on the session rather than read at approval time, so a
    plan reviewed under one set of numbers is created under the same ones even
    if the team's defaults change in between.
    """

    requirement: str = ""
    cadence: str | None = Field(
        default=None,
        description="annual, quarterly, sprint, or a range like 'epic..feature'",
    )
    buffer_factor: Decimal | None = None
    capacity_hours: Decimal | None = None
    sprint: str | None = Field(
        default=None, description="uses any capacity recorded for this sprint"
    )


class Message(BaseModel):
    text: str


class Decision(BaseModel):
    approved: bool
    note: str = ""


class PromptText(BaseModel):
    text: str


class ContextAttachment(BaseModel):
    path: Path
    name: str | None = None


class CapacityValue(BaseModel):
    hours: Decimal


# -- application ---------------------------------------------------------


def create_app(config_path: Path = composition.DEFAULT_PATH) -> FastAPI:
    """Build the API.

    A factory rather than a module-level app so the config path is an argument
    and not an import-time global — and so the composition root is still the
    only place that knows concrete classes.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Built once, at startup: a broken configuration should fail the server
        # rather than every request. The runtime is not started here — that
        # costs a process, and `/health?deep=true` is where it belongs.
        app.state.planner = composition.build(config_path)
        app.state.runs = RunRegistry()
        app.state.config_path = config_path
        try:
            yield
        finally:
            # Every live run holds a `claude` subprocess. They are ours to reap.
            await app.state.runs.shutdown()

    app = FastAPI(
        title="tech-planner",
        version="0.1.0",
        summary="Turn requirements into work items, on your Claude Code subscription.",
        lifespan=lifespan,
    )
    _register_error_handlers(app)
    _register_routes(app)
    return app


def _planner(request: Request) -> composition.Application:
    return request.app.state.planner


def _runs(request: Request) -> RunRegistry:
    return request.app.state.runs


def _register_routes(app: FastAPI) -> None:
    # -- health ----------------------------------------------------------

    @app.get("/health", tags=["health"])
    async def health(request: Request, deep: bool = False) -> dict[str, object]:
        """What the tool can see.

        Shallow by default and deliberately cheap: it resolves configuration
        and assembles the prompt, which is what most polling wants to know.
        `deep=true` additionally starts the runtime to report the MCP servers
        it reaches — accurate, but it spawns a process, so it is opt-in.
        """
        planner = _planner(request)
        prompt = planner.prompt.preview_assembled()
        report: dict[str, object] = {
            "ok": True,
            "config": str(request.app.state.config_path),
            "backend": planner.settings.backend.name,
            "profile": str(planner.settings.agent.tool_profile),
            "runtime": planner.settings.agent.binary,
            "prompt_characters": len(prompt),
            "unfilled_placeholders": list(unfilled_placeholders(prompt)),
            "active_runs": list(_runs(request).active()),
        }
        if report["unfilled_placeholders"]:
            report["ok"] = False
        if deep:
            # Reported rather than raised: a health check that 500s tells the
            # caller less than one that says which part is unreachable.
            try:
                report["mcp_servers"] = list(await planner.agent.preflight())
            except (RuntimeUnavailable, RuntimeFailed) as exc:
                report["ok"] = False
                report["runtime_error"] = str(exc)
        return report

    @app.get("/policy", tags=["health"])
    async def policy(request: Request) -> dict[str, object]:
        """The approval gate, resolved. The UI shows this on the approval card.

        Worth exposing over HTTP for the same reason the CLI prints it: a claim
        that the propose pass cannot write to the backend is only worth
        something if you can look at it.
        """
        settings = _planner(request).settings
        return {
            "profile": str(settings.agent.tool_profile),
            "backend": settings.backend.name,
            "passes": {
                str(kind): _pass_policy(kind, settings)
                for kind in (PassKind.PROPOSE, PassKind.CREATE)
            },
        }

    # -- sessions --------------------------------------------------------

    @app.get("/sessions", tags=["sessions"])
    async def list_sessions() -> list[dict[str, object]]:
        return [
            session_payload(s) for s in composition.sessions_repository().list()
        ]

    @app.post("/sessions", status_code=201, tags=["sessions"])
    async def create_session(
        request: Request, body: NewSession | None = None
    ) -> dict[str, object]:
        """Open a session. Starts no run and creates nothing.

        Preflight happens here, inside `start_session`: a session whose backend
        is unreachable would produce a confident-looking plan built on invented
        iteration paths, which is worse than refusing to open.
        """
        body = body or NewSession()
        planner = _planner(request)
        scope = (
            PlanningScope.parse(body.cadence)
            if body.cadence
            else PlanningScope.for_cadence(planner.settings.cadence)
        )
        capacity = resolve_capacity(
            planner.capacity,
            sprint=body.sprint,
            override=body.capacity_hours,
            default=planner.settings.story_capacity_hours,
        )
        started = await planner.start_session(
            body.requirement,
            scope=scope,
            buffer_factor=body.buffer_factor or planner.settings.buffer_factor,
            capacity_hours=capacity,
        )
        return session_payload(started.session, full=True) | {
            "mcp_servers": list(started.mcp_servers)
        }

    @app.get("/sessions/{session_id}", tags=["sessions"])
    async def get_session(session_id: str) -> dict[str, object]:
        session = composition.sessions_repository().get(session_id)
        return session_payload(session, full=True)

    @app.post("/sessions/{session_id}/messages", status_code=202, tags=["sessions"])
    async def send_message(
        request: Request, session_id: str, body: Message
    ) -> dict[str, object]:
        """Ask for a plan. Returns immediately; the run streams on `/events`.

        Accepted rather than awaited because a planning pass takes minutes, and
        an HTTP request held open for minutes is a request that dies to a proxy
        timeout somewhere and takes the run with it.
        """
        planner = _planner(request)
        # Fails now with a 404 rather than inside a background task, where the
        # only symptom would be an event stream that opens and says nothing.
        composition.sessions_repository().get(session_id)
        _start(request, session_id, lambda: planner.propose(session_id, body.text))
        return {"session_id": session_id, "started": True}

    @app.post("/sessions/{session_id}/approve", status_code=202, tags=["sessions"])
    async def approve(
        request: Request, session_id: str, body: Decision
    ) -> dict[str, object]:
        """Record the verdict, and on a yes run the pass that writes.

        The check below is a courtesy, not the gate: it turns an unapprovable
        plan into a 409 the UI can render instead of a failed run. The gate
        itself is `PlanningSession.decide`, which refuses regardless of who
        calls it, and the backend's write tools, which stay denied until it has.
        """
        planner = _planner(request)
        session = composition.sessions_repository().get(session_id)
        if session.status is not SessionStatus.PROPOSED:
            # There is nothing on the table to decide about. Caught here so it
            # is an HTTP error the UI can render, rather than a run that starts
            # and immediately fails inside the event stream.
            raise HTTPException(
                status_code=409,
                detail=f"session {session_id} is {session.status}; "
                "a decision can only be made on a proposed plan",
            )
        if body.approved and session.report is not None and not session.report.is_approvable:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "this plan breaks mandatory planning rules and cannot be created",
                    "errors": [v.message for v in session.report.errors],
                },
            )
        decision = (
            ApprovalDecision.approve(body.note)
            if body.approved
            else ApprovalDecision.reject(body.note)
        )
        _start(request, session_id, lambda: planner.approve(session_id, decision))
        return {"session_id": session_id, "approved": body.approved}

    @app.get("/sessions/{session_id}/events", tags=["sessions"])
    async def events(request: Request, session_id: str) -> StreamingResponse:
        """The run's events as SSE, replayed from the start.

        Replay is what makes a refresh survivable: the browser reconnects, gets
        the whole run so far, and carries on. It also means the UI needs no
        cursor and no reconciliation — the stream *is* the state.
        """
        run = _runs(request).get(session_id)
        if run is None:
            raise HTTPException(
                status_code=404, detail=f"no run has been started for session {session_id}"
            )
        return StreamingResponse(
            _stream(run, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                # Nginx buffers SSE into uselessness without this.
                "X-Accel-Buffering": "no",
            },
        )

    @app.delete("/sessions/{session_id}/run", tags=["sessions"])
    async def cancel_run(request: Request, session_id: str) -> dict[str, object]:
        """Stop a run, and with it the runtime process behind it."""
        return {"cancelled": await _runs(request).cancel(session_id)}

    # -- prompt ----------------------------------------------------------

    @app.get("/prompt", tags=["prompt"])
    async def read_prompt(request: Request) -> dict[str, object]:
        planner = _planner(request)
        assembled = planner.prompt.preview_assembled()
        return {
            # The editable half is what the textarea shows; the assembled half
            # is what the agent receives. Keeping them distinct is the whole
            # reason the backend adapter can be a document rather than code.
            "text": planner.prompt.read(),
            "assembled": assembled,
            "unfilled_placeholders": list(unfilled_placeholders(assembled)),
        }

    @app.put("/prompt", tags=["prompt"])
    async def write_prompt(request: Request, body: PromptText) -> dict[str, object]:
        """Replace the prompt. Takes effect on the next pass, not one in flight."""
        planner = _planner(request)
        planner.prompt.write(body.text)
        return {"saved": True, "characters": len(body.text)}

    # -- context files ---------------------------------------------------

    @app.get("/context", tags=["context"])
    async def list_context(request: Request) -> list[dict[str, object]]:
        return [
            {"name": f.name, "path": str(f.path), "size_bytes": f.size_bytes}
            for f in _planner(request).context.list()
        ]

    @app.post("/context", status_code=201, tags=["context"])
    async def attach_context(
        request: Request, body: ContextAttachment
    ) -> dict[str, object]:
        """Attach a document by path.

        By path rather than by upload: the agent has file tools, and naming a
        file lets it read the parts it needs instead of pushing a standards
        document through the context window on turn one.
        """
        attached = _planner(request).context.attach(body.path, name=body.name)
        return {
            "name": attached.name,
            "path": str(attached.path),
            "size_bytes": attached.size_bytes,
        }

    @app.delete("/context/{name}", status_code=204, tags=["context"])
    async def detach_context(request: Request, name: str) -> None:
        _planner(request).context.detach(name)

    # -- capacity --------------------------------------------------------

    @app.get("/capacity", tags=["capacity"])
    async def read_capacity(request: Request) -> dict[str, object]:
        planner = _planner(request)
        return {
            "default_hours": str(planner.settings.story_capacity_hours),
            "buffer_factor": str(planner.settings.buffer_factor),
            "sprints": {s: str(h) for s, h in planner.capacity.all().items()},
        }

    @app.put("/capacity/{sprint}", tags=["capacity"])
    async def set_capacity(
        request: Request, sprint: str, body: CapacityValue
    ) -> dict[str, object]:
        _planner(request).capacity.set(sprint, body.hours)
        return {"sprint": sprint, "hours": str(body.hours)}

    @app.delete("/capacity/{sprint}", status_code=204, tags=["capacity"])
    async def clear_capacity(request: Request, sprint: str) -> None:
        _planner(request).capacity.clear(sprint)


def _pass_policy(kind: PassKind, settings: Settings) -> dict[str, object]:
    permissions = permissions_for(kind, settings)
    return {
        "permission_mode": permissions.permission_mode,
        "exhaustive": permissions.exhaustive,
        "allowed": list(permissions.allowed),
        "denied": list(permissions.disallowed),
    }


def _start(request: Request, session_id: str, source: EventSource) -> None:
    try:
        _runs(request).start(session_id, source)
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _stream(run: Run, request: Request) -> AsyncIterator[str]:
    """Frame a run's events, with a keep-alive on the quiet stretches.

    The client disconnect check matters: without it a closed tab leaves this
    generator parked on `anext`, the subscriber count never drops, and the run
    it was watching is never reaped.
    """
    messages = run.subscribe()
    try:
        while True:
            try:
                name, payload = await asyncio.wait_for(
                    anext(messages), timeout=_KEEPALIVE_SECONDS
                )
            except TimeoutError:
                if await request.is_disconnected():
                    return
                yield comment("keep-alive")
                continue
            except StopAsyncIteration:
                yield sse("stream_closed", {"session_id": run.session_id})
                return
            yield sse(name, payload)
    finally:
        await messages.aclose()


def _register_error_handlers(app: FastAPI) -> None:
    """Turn the errors the core raises into answers the UI can render.

    Every one of these is something a person can act on — a session id that
    does not exist, a plan the rules refuse, a runtime that is not installed —
    so each gets its own status code rather than a shared 500 with a traceback.
    """

    @app.exception_handler(SessionNotFound)
    async def _not_found(_: Request, exc: SessionNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ContextFileNotFound)
    async def _no_file(_: Request, exc: ContextFileNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        # A rule the plan or the request breaks. The caller's to fix, not ours.
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(EmptyPrompt)
    async def _empty_prompt(_: Request, exc: EmptyPrompt) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(InvalidOperation)
    async def _bad_number(_: Request, exc: InvalidOperation) -> JSONResponse:
        return JSONResponse(
            status_code=422, content={"detail": f"not a usable number: {exc}"}
        )

    @app.exception_handler(SettingsError)
    async def _settings(_: Request, exc: SettingsError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(RuntimeUnavailable)
    async def _no_runtime(_: Request, exc: RuntimeUnavailable) -> JSONResponse:
        # 503: the tool is fine, the thing it drives is not there yet.
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(RuntimeFailed)
    async def _runtime_failed(_: Request, exc: RuntimeFailed) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})
