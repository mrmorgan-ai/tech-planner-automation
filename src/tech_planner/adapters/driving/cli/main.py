"""The command-line driving adapter.

The headless slice: everything the eventual UI will do, minus the UI. Both
adapters call the same use cases, so anything provable here — the approval gate
above all — holds there too.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from tech_planner import composition
from tech_planner.adapters.driving.cli.render import render_event, render_plan
from tech_planner.adapters.driven.claude_code.process import (
    RuntimeFailed,
    RuntimeUnavailable,
)
from tech_planner.adapters.driven.filesystem.prompt_repository import (
    unfilled_placeholders,
)
from tech_planner.adapters.driven.policy.tool_policy import permissions_for
from tech_planner.application.events import PassKind, ProposalReady, RunFailed
from tech_planner.application.ports.session_repository import SessionNotFound
from tech_planner.application.ports.settings_provider import SettingsError
from tech_planner.domain.errors import DomainError
from tech_planner.domain.model.approval import ApprovalDecision
from tech_planner.application.ports.capacity_repository import resolve_capacity
from tech_planner.domain.model.planning_session import SessionStatus
from tech_planner.domain.model.scope import PlanningScope

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOT_APPROVED = 2


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(asyncio.run(args.handler(args)))
    except (
        InvalidOperation,
        SettingsError,
        SessionNotFound,
        DomainError,
        RuntimeUnavailable,
        RuntimeFailed,
    ) as exc:
        # Every one of these is something the user can act on — a missing
        # binary, a config file that points at nothing, a session id that does
        # not exist. A traceback would bury the one line that matters.
        print(f"✗ {exc}", file=sys.stderr)
        return EXIT_FAILED
    except KeyboardInterrupt:
        # The subprocess is terminated by the gateway's own cleanup on the way
        # out, so an interrupted run does not leave a runtime behind.
        print("\ninterrupted — nothing was created", file=sys.stderr)
        return EXIT_FAILED


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tech-planner",
        description="Turn a requirement into user stories broken down as tasks.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=composition.DEFAULT_PATH,
        help="path to settings.py (default: config/settings.py)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check the runtime, auth and backend")
    doctor.set_defaults(handler=_doctor)

    plan = sub.add_parser("plan", help="plan a requirement")
    source = plan.add_mutually_exclusive_group(required=True)
    source.add_argument("requirement", nargs="?", help="the requirement, as text")
    source.add_argument("--file", type=Path, help="read the requirement from a file")
    plan.add_argument(
        "--cadence",
        default=None,
        metavar="WHICH",
        help=(
            "which planning event this is: annual (Epic->Feature), quarterly "
            "(Feature->UserStory), sprint (UserStory->Task), or an explicit "
            "range like 'epic..feature'. Decides which rules apply."
        ),
    )
    plan.add_argument(
        "--buffer",
        type=Decimal,
        default=None,
        metavar="FACTOR",
        help="contingency multiplier for this run, overriding the configured one",
    )
    plan.add_argument(
        "--capacity",
        type=Decimal,
        default=None,
        metavar="HOURS",
        help="buffered hours one story may carry, overriding sprint and config values",
    )
    plan.add_argument(
        "--sprint",
        default=None,
        metavar="NAME",
        help="sprint being planned; uses any capacity recorded for it",
    )
    plan.add_argument(
        "--yes",
        action="store_true",
        help="approve without prompting. Rules that block approval still block it.",
    )
    plan.set_defaults(handler=_plan)

    sessions = sub.add_parser("sessions", help="list past planning sessions")
    sessions.set_defaults(handler=_sessions)

    capacity = sub.add_parser("capacity", help="record capacity per sprint")
    capacity.add_argument("sprint", nargs="?", help="sprint name")
    capacity.add_argument("hours", nargs="?", type=Decimal, help="buffered hours")
    capacity.add_argument("--clear", action="store_true", help="forget this sprint")
    capacity.set_defaults(handler=_capacity)

    policy = sub.add_parser(
        "policy", help="show what each pass is permitted to do (the approval gate)"
    )
    policy.set_defaults(handler=_policy)

    prompt = sub.add_parser("prompt", help="show the system prompt the agent receives")
    prompt.add_argument(
        "--editable",
        action="store_true",
        help="show only prompts/system.md, without the backend adapter appended",
    )
    prompt.set_defaults(handler=_prompt)

    return parser


async def _doctor(args: argparse.Namespace) -> int:
    app = composition.build(args.config)
    print(f"config       {args.config}")
    print(f"backend      {app.settings.backend.name}")
    print(f"profile      {app.settings.agent.tool_profile}")
    print(f"runtime      {app.settings.agent.binary}")
    print("starting the runtime to check what it can reach…")

    started = await app.start_session()
    print("\n✓ runtime started — running on your Claude Code subscription")
    print(f"✓ session      {started.session.id}")
    print(f"✓ MCP servers  {', '.join(started.mcp_servers) or 'none'}")

    prompt = app.prompt.preview_assembled()
    print(f"✓ prompt       {len(prompt)} characters assembled")
    if unfilled := unfilled_placeholders(prompt):
        print(f"! prompt       unfilled placeholders: {', '.join(unfilled)}")
        print("               add them to backend options in your config")
        return EXIT_FAILED

    if blank := sorted(k for k, v in app.settings.backend.options.items() if not v.strip()):
        # Not fatal. An empty area path is a legitimate choice — the backend
        # has a default — but it is worth saying out loud, because the other
        # way to get an empty value here is a typo in the key name.
        print(f"! backend      configured but empty: {', '.join(blank)}")
    return EXIT_OK


async def _plan(args: argparse.Namespace) -> int:
    requirement = args.file.read_text(encoding="utf-8") if args.file else args.requirement
    app = composition.build(args.config)

    scope = (
        PlanningScope.parse(args.cadence)
        if args.cadence
        else PlanningScope.for_cadence(app.settings.cadence)
    )
    capacity = resolve_capacity(
        app.capacity,
        sprint=args.sprint,
        override=args.capacity,
        default=app.settings.story_capacity_hours,
    )
    buffer_factor = args.buffer if args.buffer is not None else app.settings.buffer_factor
    print(f"planning {scope} \u00b7 buffer x{buffer_factor}", end="")
    print(f" \u00b7 capacity {capacity}h" if scope.plans_tasks else "")

    started = await app.start_session(
        requirement,
        scope=scope,
        buffer_factor=buffer_factor,
        capacity_hours=capacity,
    )
    session_id = started.session.id
    print(f"session {session_id}\n")

    proposal = None
    async for event in app.propose(session_id, requirement):
        render_event(event)
        if isinstance(event, ProposalReady):
            proposal = event.proposal
        elif isinstance(event, RunFailed):
            return EXIT_FAILED

    if proposal is None:
        return EXIT_FAILED

    render_plan(proposal, buffer_factor)

    # The findings were already printed as they arrived, on the PlanValidated
    # event. This re-reads the session only to decide whether approval is even
    # on the table.
    session = composition.sessions_repository().get(session_id)
    assert session.report is not None

    if not session.report.is_approvable:
        # Deliberately not offered as an override. Warnings are the user's to
        # weigh; a broken mandatory rule is what this tool exists to catch.
        print("\n✗ this plan breaks mandatory planning rules and cannot be created.")
        print("  Re-run with a narrower requirement, or fix the rules it violates.")
        return EXIT_NOT_APPROVED

    if not _confirm(args.yes, len(proposal.items)):
        async for event in app.approve(session_id, ApprovalDecision.reject("declined")):
            render_event(event)
        return EXIT_NOT_APPROVED

    print()
    async for event in app.approve(session_id, ApprovalDecision.approve()):
        render_event(event)
        if isinstance(event, RunFailed):
            return EXIT_FAILED

    session = composition.sessions_repository().get(session_id)
    if session.status is not SessionStatus.CREATED:
        return EXIT_FAILED

    print(f"\n✓ created {len(session.created)} work items")
    for item in session.created:
        print(f"  {item.ref:<12} {item.backend_id}" + (f"  {item.url}" if item.url else ""))
    return EXIT_OK


def _confirm(assume_yes: bool, item_count: int) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        # Refusing beats guessing. Creation is irreversible in practice, and a
        # piped run that silently created forty work items would be worse than
        # one that stopped.
        print("\n✗ not a terminal, so approval cannot be given. Re-run with --yes.")
        return False
    answer = input(f"\nCreate these {item_count} work items? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


async def _capacity(args: argparse.Namespace) -> int:
    """Record what a given sprint can actually take on.

    Its own command because capacity changes roughly every two weeks — holidays,
    a support rotation, a short week — which is far too often to be editing a
    config file by hand.
    """
    repository = composition.capacity_repository()
    if args.sprint and args.clear:
        repository.clear(args.sprint)
        print(f"cleared {args.sprint}")
        return EXIT_OK
    if args.sprint and args.hours is not None:
        repository.set(args.sprint, args.hours)
        print(f"{args.sprint}: {args.hours}h")
        return EXIT_OK

    recorded = repository.all()
    if not recorded:
        print("no per-sprint capacity recorded; the configured default applies")
        return EXIT_OK
    for sprint, hours in recorded.items():
        print(f"{sprint:<24} {hours}h")
    return EXIT_OK


async def _sessions(_: argparse.Namespace) -> int:
    sessions = composition.sessions_repository().list()
    if not sessions:
        print("no sessions yet")
        return EXIT_OK
    for session in sessions:
        headline = (session.requirement or "").splitlines()[0][:60] if session.requirement else ""
        print(f"{session.id}  {str(session.status):<9}  {headline}")
    return EXIT_OK


async def _policy(args: argparse.Namespace) -> int:
    """Print the gate, so it can be inspected instead of taken on trust.

    Spawns nothing and contacts nothing — this is pure resolution of settings
    into tool permissions, which makes it the cheapest way to confirm that a
    propose pass genuinely cannot write to the backend.
    """
    app = composition.build(args.config)
    print(f"profile  {app.settings.agent.tool_profile}")
    print(f"backend  {app.settings.backend.name}\n")

    for kind in (PassKind.PROPOSE, PassKind.CREATE):
        permissions = permissions_for(kind, app.settings)
        guarantee = (
            "exhaustive allow-list — writes impossible by construction"
            if permissions.exhaustive
            else "deny-list — best-effort, see tool_policy.py"
        )
        print(f"{str(kind).upper()}  (--permission-mode {permissions.permission_mode})")
        print(f"  guarantee   {guarantee}")
        print(f"  allowed     {_names(permissions.allowed) or 'inherits your environment'}")
        print(f"  denied      {_names(permissions.disallowed) or 'nothing'}")
        print()
    return EXIT_OK


def _names(names: tuple[str, ...]) -> str:
    return ("\n" + " " * 14).join(names)


async def _prompt(args: argparse.Namespace) -> int:
    app = composition.build(args.config)
    print(app.prompt.read() if args.editable else app.prompt.preview_assembled())
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
