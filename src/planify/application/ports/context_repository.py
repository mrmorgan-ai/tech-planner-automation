"""Attached context documents — the spec's "Files section".

Requirement docs, backlogs, architecture notes, standards. These are *inputs*
the user curates, in the spirit of a project's files: first-class and visible,
not a hidden setting.

They are attached by path rather than read into the request. The agent has file
tools; handing it a path lets it read what it needs when it needs it, instead
of pushing a 200-page standards document through the context window on turn one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ContextFile:
    name: str
    path: Path
    size_bytes: int = 0


@runtime_checkable
class ContextRepository(Protocol):
    def list(self) -> tuple[ContextFile, ...]: ...

    def add(self, source: Path, *, name: str | None = None) -> ContextFile:
        """Attach a document, copying it into the session's context store."""
        ...

    def remove(self, name: str) -> None: ...
