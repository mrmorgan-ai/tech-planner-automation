"""Attach and remove context documents — the spec's "Files section"."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from planify.application.ports.context_repository import ContextFile, ContextRepository


class ContextFileNotFound(FileNotFoundError):
    """The path offered for attachment does not exist."""


@dataclass(frozen=True, slots=True)
class ManageContextFiles:
    context: ContextRepository

    def list(self) -> tuple[ContextFile, ...]:
        return self.context.list()

    def attach(self, source: Path, *, name: str | None = None) -> ContextFile:
        source = Path(source).expanduser()
        if not source.is_file():
            raise ContextFileNotFound(f"no such file: {source}")
        return self.context.add(source, name=name)

    def detach(self, name: str) -> None:
        self.context.remove(name)
