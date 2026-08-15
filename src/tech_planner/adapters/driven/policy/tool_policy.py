"""What a pass is permitted to do — the propose/create gate, as a tool list.

**The finding this module is built around.** Denying a *tool* does not deny a
*capability*. In a live check, denying ``Bash`` did take effect, and the agent
completed the same shell command through ``Monitor`` instead — not to evade the
restriction, but because a sibling tool offering the same capability was still
available. Nothing about that was adversarial, which is exactly why it matters.

The consequence for the propose pass is direct: blocking the backend's five
mutating MCP tools is not sufficient on its own, because a work-tracking
backend also has a documented REST API, and anything that can execute a command
can reach it. So the deny list covers the capability family, not just the tools
we wish were the only way in.

**What this does and does not guarantee.** Under ``OPEN``, this is best-effort
and deliberately so: the user's whole environment stays available for research,
and a future MCP server with its own exec or HTTP capability could offer a path
this list does not name. Under ``STRICT``, the pass runs an exhaustive
allow-list and creating anything is impossible by construction. ``OPEN`` is the
default because it is what the tool is for; ``STRICT`` exists for when
best-effort is not good enough.

Either way, this is only half the gate. The other half is
`PlanningSession.decide`, which refuses to reach a create pass at all without a
recorded approval. Neither half is trusted alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from tech_planner.adapters.driven.policy.backend_tools import BackendTools, tools_for
from tech_planner.application.events import PassKind
from tech_planner.application.settings import Settings, ToolProfile

#: Tools that can run a command or write a file, and therefore can reach a
#: backend's REST API without touching its MCP server. Denied in both passes:
#: the propose pass must not create, and the create pass has no business
#: running shell commands either.
#:
#: ``WebFetch`` is deliberately absent. It retrieves rather than submits, and
#: denying it would cost the agent the ability to read linked requirement
#: documents during planning. A team that considers that too generous can add
#: it through ``extra_denied_tools`` rather than by editing this list.
EXEC_CAPABLE_TOOLS: tuple[str, ...] = (
    "Bash",
    "Monitor",
    "Write",
    "Edit",
    "NotebookEdit",
)

#: The read-only built-ins a STRICT pass still needs to ground its estimates in
#: the repositories exposed via ``--add-dir``.
READ_ONLY_BUILTINS: tuple[str, ...] = ("Read", "Glob", "Grep")

#: Structured output is delivered by calling a tool, not by writing text —
#: observed directly in a live run, where the plan arrived via a
#: ``StructuredOutput`` tool call and the run ended with ``stop_reason:
#: "tool_use"``. An exhaustive allow-list that omits it would therefore block
#: the pass from returning its answer at all, which is a failure mode that
#: looks like a model problem and is not one.
STRUCTURED_OUTPUT_TOOL = "StructuredOutput"


@dataclass(frozen=True, slots=True)
class ToolPermissions:
    """Resolved permissions for one pass, including the mode they rely on."""

    #: Runtime permission mode. This is not cosmetic: it decides what happens
    #: to a tool that appears in neither list, and the two profiles need
    #: opposite answers to that question.
    permission_mode: str
    allowed: tuple[str, ...] = ()
    disallowed: tuple[str, ...] = ()
    #: True when the allow-list is the complete set of what the pass can reach,
    #: so creation is impossible by construction rather than by enumeration.
    exhaustive: bool = False


def permissions_for(kind: PassKind, settings: Settings) -> ToolPermissions:
    """Work out what this pass may touch."""
    backend = tools_for(settings.backend.name)
    if settings.agent.tool_profile is ToolProfile.STRICT:
        return _strict(kind, backend, settings)
    return _open(kind, backend, settings)


def _open(kind: PassKind, backend: BackendTools, settings: Settings) -> ToolPermissions:
    """Everything the user has, minus what we explicitly take away.

    The permission mode has to be ``bypassPermissions`` rather than
    ``dontAsk``, and the reason is not convenience. Under ``dontAsk`` a tool
    that matches no rule is refused, so an OPEN pass would silently lose every
    MCP server the user has not already added to their own ``permissions.allow``
    — which is most of them, for anyone who answers prompts interactively. The
    profile would then claim to inherit the user's environment while quietly
    running without it.

    This is safe here only because of the same live check that motivated the
    deny list: ``--disallowedTools`` is honoured *under* ``bypassPermissions``.
    Denial takes precedence, so the rules below are not advisory.
    """
    denied = list(EXEC_CAPABLE_TOOLS)
    denied.extend(settings.agent.extra_denied_tools)
    if kind is PassKind.PROPOSE:
        denied.extend(backend.qualified_mutating)

    return ToolPermissions(
        permission_mode="bypassPermissions",
        allowed=_dedupe(list(settings.agent.extra_allowed_tools)),
        disallowed=_dedupe(denied),
        exhaustive=False,
    )


def _strict(kind: PassKind, backend: BackendTools, settings: Settings) -> ToolPermissions:
    """Only what is named, and nothing else.

    ``dontAsk`` is the right mode here for the reason it is wrong above: a tool
    matching no rule is refused. There is no human on the other end of a print
    mode run, so an unmatched tool must fail rather than wait.
    """
    allowed = list(backend.qualified_reading)
    allowed.extend(READ_ONLY_BUILTINS)
    allowed.append(STRUCTURED_OUTPUT_TOOL)
    allowed.extend(settings.agent.extra_allowed_tools)
    denied = list(EXEC_CAPABLE_TOOLS) + list(settings.agent.extra_denied_tools)

    if kind is PassKind.CREATE:
        allowed.extend(backend.qualified_mutating)
    else:
        # Redundant next to an exhaustive allow-list, and kept anyway: if the
        # allow-list is ever widened through `extra_allowed_tools`, this is what
        # still stops a propose pass from writing.
        denied.extend(backend.qualified_mutating)

    return ToolPermissions(
        permission_mode="dontAsk",
        allowed=_dedupe(allowed),
        disallowed=_dedupe(denied),
        exhaustive=True,
    )


def _dedupe(names: list[str]) -> tuple[str, ...]:
    """Order-preserving deduplication, so the command line stays readable."""
    return tuple(dict.fromkeys(names))
