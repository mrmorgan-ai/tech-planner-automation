"""Command-line construction. The only module that knows the runtime's flags.

The agent runtime ships often and its flag surface moves with it. Keeping every
flag in one file means an upgrade that renames something is a small, obvious
diff here instead of a hunt through the codebase — which is the whole reason
the agent is behind a port at all.

Every flag below is present or absent on purpose; the omissions matter as much
as the inclusions, and are recorded in `_OMITTED_ON_PURPOSE`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from planify.adapters.driven.claude_code.schema import (
    creation_report_schema,
    plan_proposal_schema,
)
from planify.adapters.driven.policy.tool_policy import permissions_for
from planify.application.events import PassKind
from planify.application.ports.agent_gateway import AgentRequest
from planify.application.settings import Settings

#: Passed via `--settings` as inline JSON. This is what stands in for `--bare`.
#:
#: `--bare` is the documented way to run the runtime clean, and it is unusable
#: here: its authentication is strictly an API key, and OAuth and the keychain
#: are never read. This tool runs on the user's own subscription, so `--bare`
#: would defeat its central premise.
#:
#: These two keys achieve the half of `--bare` we actually want — no memory
#: files injected from anywhere — while leaving MCP servers, plugins and skills
#: untouched. That is the whole "isolate instructions, inherit capabilities"
#: principle, expressed in two settings.
ISOLATION_SETTINGS: dict[str, Any] = {
    "autoMemoryEnabled": False,
    "claudeMdExcludes": ["**/CLAUDE.md", "**/.claude/CLAUDE.md"],
}

#: Environment variables removed from the child process.
#:
#: The tool runs on the user's Claude Code subscription — the runtime is already
#: signed in, and that sign-in is what pays for and authorises every run. The
#: first two are cleared because the runtime would prefer them if present and
#: silently bill somewhere else instead, with nothing in the output to show it.
#: Clearing them makes "this runs on your subscription" true by construction
#: rather than something to check by hand.
#:
#: The last one is removed because `--add-dir` directories do not contribute
#: their memory files unless it is set. Our instruction-isolation guarantee
#: depends on it staying unset, so we unset it rather than hope.
STRIPPED_ENV_VARS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD",
)

#: Flags deliberately not used, and why. Kept as code so the reasoning survives
#: the next person who wonders whether to add them.
_OMITTED_ON_PURPOSE = {
    "--bare": "forces API-key auth; OAuth and keychain are never read",
    "--strict-mcp-config": "would drop every MCP server the user has installed",
    "--disable-slash-commands": "would drop the user's own commands and skills",
    "--tools": "restricts the toolset outright, stripping the user's environment",
    "--append-system-prompt": "we replace the default prompt rather than add to it",
    "--replay-user-messages": "we already know what we sent; echoing it back is noise",
}


@dataclass(frozen=True, slots=True)
class Launch:
    """A fully-resolved subprocess invocation."""

    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    #: True when the pass is permitted to write to the backend. Carried so the
    #: caller can log it, and so a create pass is never launched by accident.
    may_mutate: bool

    def redacted(self) -> str:
        """The command line, for logs and `doctor` output."""
        return " ".join(self.argv)


def build_launch(
    request: AgentRequest,
    settings: Settings,
    *,
    system_prompt_path: Path,
    interactive: bool = False,
) -> Launch:
    agent = settings.agent
    permissions = permissions_for(request.kind, settings)

    # Interactive runs take their turns on stdin instead of the command line,
    # so `-p` carries no prompt. The first turn is written in by the caller the
    # moment the process is up, which keeps one code path for every turn rather
    # than making the first one special.
    argv: list[str] = [agent.binary, "-p"]
    if interactive:
        argv += ["--input-format", "stream-json"]
    else:
        argv.append(turn_text(request))

    # Machine-readable streaming. `--verbose` is required for stream-json to
    # emit anything beyond the final result.
    argv += ["--output-format", "stream-json", "--verbose", "--include-partial-messages"]

    # Structured output. Verified compatible with stream-json: the payload
    # arrives as `structured_output` on the result message. Note the flag takes
    # inline JSON, not a path — unlike --system-prompt-file next to it.
    argv += ["--json-schema", json.dumps(_schema_for(request), separators=(",", ":"))]

    # The tool's own instructions, replacing the runtime's default entirely.
    argv += ["--system-prompt-file", str(system_prompt_path)]

    argv += ["--settings", json.dumps(ISOLATION_SETTINGS, separators=(",", ":"))]

    # User scope only. Project and local scopes are excluded so that this
    # repository's own settings and hooks never execute: print mode shows no
    # trust prompt, so a project hook would otherwise run unannounced.
    argv += ["--setting-sources", "user"]

    # Paths are made absolute before they go on the command line. The runtime
    # runs with `cwd` set to the workspace directory, so a relative path here
    # would be resolved against *that* rather than against the project — which
    # fails as "MCP config file not found: .../workspace/.mcp.json".
    if settings.backend.mcp_config is not None:
        # Added *on top of* the user's own servers. Deliberately not paired
        # with --strict-mcp-config.
        argv += ["--mcp-config", str(settings.backend.mcp_config.resolve())]

    for directory in agent.add_dirs:
        argv += ["--add-dir", str(directory.resolve())]

    # We assign the session id rather than reading it back out of the stream,
    # so resuming never depends on having parsed a particular event.
    argv += ["--resume", request.session_id] if request.resume else [
        "--session-id",
        request.session_id,
    ]

    argv += ["--permission-mode", permissions.permission_mode]
    if permissions.allowed:
        argv += ["--allowedTools", *permissions.allowed]
    if permissions.disallowed:
        argv += ["--disallowedTools", *permissions.disallowed]

    if agent.model:
        argv += ["--model", agent.model]

    return Launch(
        argv=tuple(argv),
        cwd=agent.workspace.resolve(),
        env=child_env(),
        may_mutate=request.kind is PassKind.CREATE,
    )


def child_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment the runtime is launched with.

    Inherits the user's environment — that is how their MCP servers find their
    own credentials — minus the variables in :data:`STRIPPED_ENV_VARS`, plus
    anything in a local `.env`.
    """
    env = dict(os.environ if base is None else base)
    # A real shell export wins over the file: if both are set, the one you just
    # typed is the one you meant.
    for name, value in load_dotenv().items():
        env.setdefault(name, value)
    for name in STRIPPED_ENV_VARS:
        env.pop(name, None)
    return env


def load_dotenv(path: Path = Path(".env")) -> dict[str, str]:
    """Read `KEY=value` lines from a local `.env`, if there is one.

    Backend credentials have to reach the MCP server somehow, and a gitignored
    `.env` beside the config is where people put them. Supporting it here means
    a PAT never has to be pasted into a tracked file, and never has to be
    re-exported in every new shell.

    Hand-rolled rather than adding a dependency: the format this needs is one
    `KEY=value` per line, `#` for comments, optional surrounding quotes. A line
    without an `=` is skipped — a bare secret in a file is not a variable, and
    guessing which variable it was meant to be would be worse than ignoring it.
    """
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        value = value.strip().strip("'\"")
        if name:
            values[name] = value
    return values


def _schema_for(request: AgentRequest) -> dict[str, Any]:
    if request.kind is PassKind.PROPOSE:
        return plan_proposal_schema(request.scope)
    return creation_report_schema()


def turn_text(request: AgentRequest) -> str:
    """The user turn, with any attached context documents named as paths.

    The files are named rather than inlined. The agent has file tools, and
    pushing a long standards document through the context window on turn one
    costs more than letting it read the parts it needs.
    """
    parts = [request.prompt, "", _brief(request)]
    if request.context_files:
        listing = "\n".join(f"- {path}" for path in request.context_files)
        parts += ["", f"Context documents available to read:\n{listing}"]
    return "\n".join(parts)


def _brief(request: AgentRequest) -> str:
    """The run's planning parameters, stated in the turn rather than the prompt.

    These change per run — the cadence you are in, the contingency factor in
    force — while the system prompt is the user's own standing instructions.
    Putting them here keeps the editable prompt free of run-specific noise.
    """
    if request.kind is not PassKind.PROPOSE:
        return ""

    scope = request.scope
    levels = " then ".join(str(level) for level in scope.levels)
    lines = [
        "For this plan:",
        f"- Produce these levels only: {levels}. Do not produce any other level.",
    ]
    if scope.plans_tasks:
        lines.append(
            f"- Size every Task in hours. final_estimate_hours = "
            f"base_estimate_hours x {request.buffer_factor}."
        )
        if request.capacity_hours is not None:
            # The number the plan is judged against, given to the agent rather
            # than kept for the verdict. "Stories must fit a sprint" is not
            # actionable without it, and a story found to be 40 hours too big
            # after the fact costs a whole turn to fix.
            lines.append(
                f"- No User Story may exceed {request.capacity_hours} buffered "
                f"hours — that is one sprint. Add up its Tasks' final hours "
                f"before you settle on the split, and if a story goes over, "
                f"split it into stories that each deliver a verifiable result."
            )
    else:
        lines.append(
            f"- There are no Tasks at this level, so give no hours. Size each "
            f"{scope.sizing_level} in story points instead."
        )
    lines.append(
        f"- Give every {scope.describable_level} acceptance criteria."
    )
    lines.append(
        "- If this message is not a requirement you can plan — a greeting, a "
        "question, or a scope too vague to size — reply in words, ask for what "
        "you need, and return an empty items array. Do not invent a "
        "placeholder plan to have something to return."
    )
    return "\n".join(lines)
