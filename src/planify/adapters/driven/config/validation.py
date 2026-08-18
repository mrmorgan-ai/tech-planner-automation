"""Checks a `Settings` object has to pass before anything runs on it.

Separate from loading because they are different jobs: `py_settings` decides
whether the file *produced* a `Settings`, and this decides whether that
`Settings` describes a working setup. The failures caught here — a missing MCP
config, a repository path that no longer exists, a placeholder nobody filled in
— are the ones whose symptoms otherwise appear much later and look like
something else.

Everything raises `SettingsError`, which the CLI turns into one line rather than
a traceback: these are all things the user fixes by editing a file.
"""

from __future__ import annotations

from pathlib import Path

from planify.application.ports.settings_provider import SettingsError
from planify.application.settings import Settings


def validate(settings: Settings, source: Path) -> Settings:
    """Return `settings` if it is usable, or explain why it is not."""
    _check_backend(settings, source)
    _check_agent(settings, source)
    _check_planning(settings, source)
    return settings


def _check_backend(settings: Settings, source: Path) -> None:
    mcp_config = settings.backend.mcp_config
    if mcp_config is not None and not mcp_config.is_file():
        raise SettingsError(
            f"backend.mcp_config in {source} points at {mcp_config}, which does not exist"
        )

    # Unfilled template markers are the likeliest misconfiguration, and the
    # failure they otherwise cause is a plan full of "<YOUR-ORG>" — produced
    # confidently, and only obvious once it reaches the board.
    unfilled = sorted(
        key
        for key, value in settings.backend.options.items()
        if value.startswith("<") and value.endswith(">")
    )
    if unfilled:
        raise SettingsError(
            f"these backend settings in {source} still hold template placeholders: "
            + ", ".join(unfilled)
        )


def _check_agent(settings: Settings, source: Path) -> None:
    missing = [str(path) for path in settings.agent.add_dirs if not path.is_dir()]
    if missing:
        raise SettingsError(
            f"agent.add_dirs in {source} names directories that do not exist: "
            + ", ".join(missing)
        )


def _check_planning(settings: Settings, source: Path) -> None:
    if settings.story_capacity_hours <= 0:
        raise SettingsError(
            f"story_capacity_hours in {source} must be positive, got "
            f"{settings.story_capacity_hours}"
        )
