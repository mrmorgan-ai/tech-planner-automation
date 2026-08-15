"""Translate the runtime's stdout messages into our own events.

This is the containment boundary. Everything upstream of here speaks the
runtime's schema, which changes between releases; everything downstream speaks
`application.events`, which changes when we decide it does.

Two rules make that containment hold:

* **Unknown message types are ignored, never fatal.** A new event type in a
  future release must not break a planning run.
* **Silence is never success.** The runtime has three ways to finish a
  structured-output run and two of them are failures — including one that
  reports ``subtype: "success"`` while returning no structured output at all.
  That case is treated as a failure here, because a plan we did not receive
  must never be mistaken for a plan with nothing in it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from tech_planner.adapters.driven.claude_code.dto import (
    MalformedProposal,
    parse_creation_report,
    parse_proposal,
)
from tech_planner.application.events import (
    AgentRetrying,
    AssistantDelta,
    AssistantMessage,
    CreationReported,
    Event,
    Notice,
    PassKind,
    ProposalReady,
    RunFailed,
    RunStarted,
    ToolFinished,
    ToolStarted,
)

#: MCP server states that mean the server is usable.
_HEALTHY = {"connected", "ready", "ok"}


class StreamMapper:
    """Stateful mapper for one pass. Not reusable across runs."""

    def __init__(
        self,
        kind: PassKind,
        *,
        session_id: str,
        required_servers: tuple[str, ...] = (),
    ) -> None:
        self._kind = kind
        self._session_id = session_id
        #: MCP servers this pass genuinely depends on — in practice, the
        #: work-tracking backend's. Only these are fatal when unhealthy.
        self._required_servers = required_servers
        self._saw_terminal = False

    @property
    def saw_terminal(self) -> bool:
        """Whether a terminal event was produced.

        The process wrapper checks this after the stream closes: a run that
        ended without one has failed, however calmly it exited.
        """
        return self._saw_terminal

    def map(self, message: Mapping[str, Any]) -> Iterator[Event]:
        match message.get("type"):
            case "system":
                yield from self._system(message)
            case "assistant":
                yield from self._assistant(message)
            case "user":
                yield from self._user(message)
            case "stream_event":
                yield from self._partial(message)
            case "rate_limit_event":
                yield from self._rate_limit(message)
            case "result":
                yield from self._result(message)
            case _:
                # Deliberately silent. An unrecognised message is a runtime we
                # have not caught up with, not a failed plan.
                return

    # -- system ----------------------------------------------------------

    def _system(self, message: Mapping[str, Any]) -> Iterator[Event]:
        subtype = message.get("subtype")
        if subtype == "api_retry":
            yield AgentRetrying(
                reason=str(message.get("message") or "the runtime is retrying"),
                attempt=int(message.get("attempt") or 1),
            )
            return
        if subtype != "init":
            return

        servers = _server_names(message.get("mcp_servers"))
        unhealthy = _unhealthy_servers(message)

        # Only the backend is load-bearing. A misconfigured MCP server is
        # skipped silently and the run carries on, which for the *backend* is
        # the worst possible default: the agent would plan against something it
        # cannot reach and invent iteration paths that look entirely plausible.
        #
        # For every other server it is normal noise. A developer's environment
        # routinely has connectors sitting in `needs-auth` that have nothing to
        # do with planning, and failing the run over them would make the tool
        # unusable. Those are reported and stepped over.
        blocking = tuple(
            detail for name, detail in unhealthy.items() if name in self._required_servers
        )
        if blocking:
            self._saw_terminal = True
            yield RunFailed(
                reason=(
                    "the work-tracking backend's MCP server is unavailable: "
                    + ", ".join(blocking)
                    + ". Planning was stopped rather than run against a backend "
                    "that cannot be reached."
                ),
                retryable=False,
            )
            return

        if incidental := tuple(
            detail
            for name, detail in unhealthy.items()
            if name not in self._required_servers
        ):
            yield Notice(
                message="MCP servers unavailable (not required for planning): "
                + ", ".join(sorted(incidental)),
                level="info",
            )

        raw_tools = message.get("tools")
        yield RunStarted(
            session_id=self._session_id,
            kind=self._kind,
            model=_text_or_none(message.get("model")),
            mcp_servers=servers,
            tools=tuple(str(t) for t in raw_tools) if isinstance(raw_tools, list) else (),
            resumed=bool(message.get("resumed")),
        )

    # -- conversation ----------------------------------------------------

    def _assistant(self, message: Mapping[str, Any]) -> Iterator[Event]:
        for block in _content(message):
            match block.get("type"):
                case "text":
                    if text := str(block.get("text") or "").strip():
                        yield AssistantMessage(text=text)
                case "tool_use":
                    yield ToolStarted(
                        name=str(block.get("name") or "tool"),
                        detail=_summarize(block.get("input")),
                    )

    def _user(self, message: Mapping[str, Any]) -> Iterator[Event]:
        for block in _content(message):
            if block.get("type") != "tool_result":
                continue
            yield ToolFinished(
                name=str(block.get("name") or "tool"),
                ok=not bool(block.get("is_error")),
                detail=_summarize(block.get("content")),
            )

    def _partial(self, message: Mapping[str, Any]) -> Iterator[Event]:
        event = message.get("event")
        if not isinstance(event, Mapping):
            return
        delta = event.get("delta")
        if isinstance(delta, Mapping) and delta.get("type") == "text_delta":
            if text := str(delta.get("text") or ""):
                yield AssistantDelta(text=text)

    def _rate_limit(self, message: Mapping[str, Any]) -> Iterator[Event]:
        info = message.get("rate_limit_info")
        if not isinstance(info, Mapping):
            return
        status = str(info.get("status") or "")
        if status and status != "allowed":
            # Worth surfacing rather than swallowing: on a subscription this is
            # the signal that matters, and a long backoff is otherwise
            # indistinguishable from the tool having hung.
            yield AgentRetrying(
                reason=f"rate limit {status} ({info.get('rateLimitType') or 'unknown window'})"
            )

    # -- terminal --------------------------------------------------------

    def _result(self, message: Mapping[str, Any]) -> Iterator[Event]:
        self._saw_terminal = True

        if denials := message.get("permission_denials"):
            # In a propose pass this is the gate working, and it is worth
            # saying so out loud rather than leaving it to be inferred.
            names = ", ".join(sorted({_denied_name(d) for d in denials}))
            yield Notice(message=f"tool calls refused by policy: {names}", level="info")

        subtype = str(message.get("subtype") or "")
        if subtype == "error_max_structured_output_retries":
            yield RunFailed(
                reason=(
                    "the agent could not produce output matching the required "
                    "schema within its retry budget"
                ),
                retryable=True,
            )
            return

        if message.get("is_error") or subtype.startswith("error"):
            yield RunFailed(
                reason=_text_or_none(message.get("result")) or f"the run failed ({subtype})",
                retryable=True,
            )
            return

        payload = message.get("structured_output")
        if not isinstance(payload, Mapping):
            yield RunFailed(
                reason=(
                    "the run reported success but returned no structured output; "
                    "no plan was produced"
                ),
                retryable=True,
            )
            return

        try:
            yield from self._terminal_from(payload)
        except MalformedProposal as exc:
            yield RunFailed(reason=str(exc), retryable=True)

    def _terminal_from(self, payload: Mapping[str, Any]) -> Iterator[Event]:
        if self._kind is PassKind.PROPOSE:
            parsed = parse_proposal(payload)
            yield ProposalReady(proposal=parsed.proposal, notes=parsed.notes)
            return

        created = parse_creation_report(payload)
        if not created:
            raise MalformedProposal(
                "the create pass returned an empty list of created work items"
            )
        yield CreationReported(items=created)


# -- helpers -------------------------------------------------------------


def _content(message: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    inner = message.get("message")
    if not isinstance(inner, Mapping):
        return []
    content = inner.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, Mapping)]


def _server_names(servers: Any) -> tuple[str, ...]:
    if not isinstance(servers, list):
        return ()
    return tuple(
        str(s.get("name")) for s in servers if isinstance(s, Mapping) and s.get("name")
    )


def _unhealthy_servers(message: Mapping[str, Any]) -> dict[str, str]:
    """Server name -> human-readable status, for every server not usable."""
    unhealthy: dict[str, str] = {}
    servers = message.get("mcp_servers")
    if isinstance(servers, list):
        for server in servers:
            if not isinstance(server, Mapping):
                continue
            name = str(server.get("name") or "")
            status = str(server.get("status") or "").lower()
            if name and status and status not in _HEALTHY:
                unhealthy[name] = f"{name} ({status})"

    errors = message.get("mcp_server_errors")
    if isinstance(errors, Mapping):
        for name, detail in errors.items():
            unhealthy[str(name)] = f"{name} ({detail})"
    elif isinstance(errors, list):
        for entry in errors:
            name = (
                str(entry.get("name") or entry)
                if isinstance(entry, Mapping)
                else str(entry)
            )
            unhealthy[name] = str(entry)
    return unhealthy


def _denied_name(denial: Any) -> str:
    if isinstance(denial, Mapping):
        return str(denial.get("tool_name") or denial.get("tool") or "unknown tool")
    return str(denial)


def _text_or_none(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _summarize(value: Any, limit: int = 160) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
