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

import tech_planner


def check_imports() -> list[str]:
    """Import every module. Catches cycles and bad wiring that tests would not."""
    failures: list[str] = []
    for module in pkgutil.walk_packages(tech_planner.__path__, "tech_planner."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # noqa: BLE001 - reporting, not handling
            failures.append(f"{module.name}: {exc!r}")
    return failures


def check_config(path: Path) -> str:
    from tech_planner.adapters.driven.config.py_settings import PySettingsProvider

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
    from tech_planner.adapters.driven.config.py_settings import PySettingsProvider
    from tech_planner.adapters.driven.policy.backend_tools import tools_for
    from tech_planner.adapters.driven.policy.tool_policy import permissions_for
    from tech_planner.application.events import PassKind

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
