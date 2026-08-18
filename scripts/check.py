"""Fast offline check: does the codebase load, and does the config make sense?

Spawns no agent and contacts nothing. This is the tight loop — run it after any
change to catch an import cycle, a broken adapter wiring, or a configuration
that will fail three minutes into a planning run.

Run via `make check`.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

import planify


def check_imports() -> list[str]:
    """Import every module. Catches cycles and bad wiring that tests would not."""
    failures: list[str] = []
    for module in pkgutil.walk_packages(planify.__path__, "planify."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # noqa: BLE001 - reporting, not handling
            failures.append(f"{module.name}: {exc!r}")
    return failures


def check_config(path: Path) -> str:
    from planify.adapters.driven.config.py_settings import PySettingsProvider

    settings = PySettingsProvider(path=path).load()
    backend = settings.backend
    reach = "configured" if backend.mcp_config else "not wired up yet"
    return (
        f"{backend.name} ({reach}), profile {settings.agent.tool_profile}, "
        f"capacity {settings.story_capacity_hours}h"
    )


def check_gate(path: Path) -> list[str]:
    """Confirm a propose pass cannot reach the backend's write tools.

    The single most important property in the system, and the cheapest one to
    verify: it is pure settings resolution, no subprocess involved.
    """
    from planify.adapters.driven.config.py_settings import PySettingsProvider
    from planify.adapters.driven.policy.backend_tools import tools_for
    from planify.adapters.driven.policy.tool_policy import permissions_for
    from planify.application.events import PassKind

    settings = PySettingsProvider(path=path).load()
    mutating = set(tools_for(settings.backend.name).qualified_mutating)

    propose = permissions_for(PassKind.PROPOSE, settings)
    problems: list[str] = []

    reachable = mutating - set(propose.disallowed)
    if propose.exhaustive:
        reachable &= set(propose.allowed)
    if reachable:
        problems.append(
            "a propose pass can reach backend write tools: " + ", ".join(sorted(reachable))
        )

    create = permissions_for(PassKind.CREATE, settings)
    if mutating & set(create.disallowed):
        problems.append("a create pass is denied the write tools it needs")
    return problems


def check_api(path: Path) -> str:
    """Build the HTTP adapter and run one fake pass through its plumbing.

    No agent and no server: a stub event source stands in for a planning run,
    which exercises the parts with no other cheap check — event serialization,
    replay to a late subscriber, and the reaping that stops a run when the last
    reader goes away. Those only otherwise fail in front of a browser.
    """
    import asyncio

    from planify.adapters.driving.http.api import create_app
    from planify.adapters.driving.http.runs import RunRegistry
    from planify.adapters.driving.http.serialization import sse
    from planify.application.events import Notice, ProposalReady
    from planify.domain.model.plan_proposal import PlanProposal
    from planify.domain.model.work_item import UserStory

    app = create_app(path)
    routes = sum(1 for r in app.routes if getattr(r, "methods", None))

    async def source():
        yield Notice(message="stub run")
        yield ProposalReady(
            proposal=PlanProposal(items=(UserStory(ref="US-1", title="Stub"),))
        )

    async def exercise() -> int:
        runs = RunRegistry()
        run = runs.start("stub", source)
        await run.wait()
        # Subscribing after the run finished must still replay all of it —
        # that is what lets a browser refresh mid-plan without losing it.
        frames = [sse(name, payload) async for name, payload in run.subscribe()]
        await runs.shutdown()
        return len(frames)

    frames = asyncio.run(exercise())
    if frames < 2:
        raise AssertionError(f"a finished run replayed {frames} events, expected 2")
    return f"{routes} routes, run replay and teardown clean"


def main() -> int:
    config = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config/settings.py")

    failures = check_imports()
    if failures:
        for failure in failures:
            print(f"FAIL  {failure}")
        return 1
    print("modules      all import cleanly")

    try:
        print(f"config       {check_config(config)}")
    except Exception as exc:  # noqa: BLE001 - the message is the whole point
        print(f"FAIL  config  {exc}")
        return 1

    problems = check_gate(config)
    for problem in problems:
        print(f"FAIL  gate    {problem}")
    if problems:
        return 1
    print("gate         propose cannot write; create can")

    try:
        print(f"api          {check_api(config)}")
    except Exception as exc:  # noqa: BLE001 - the message is the whole point
        print(f"FAIL  api     {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
