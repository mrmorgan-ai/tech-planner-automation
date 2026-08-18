"""Where configuration comes from.

A port rather than a direct file read so the core never learns that settings
live in TOML, and so a test can hand over a `Settings` object without touching
a filesystem.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from planify.application.settings import Settings


class SettingsError(RuntimeError):
    """Configuration is missing or unusable."""


@runtime_checkable
class SettingsProvider(Protocol):
    def load(self) -> Settings:
        """Raise :class:`SettingsError` rather than returning half a config."""
        ...
