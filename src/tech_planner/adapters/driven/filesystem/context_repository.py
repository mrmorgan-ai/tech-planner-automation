"""Attached context documents, stored as a flat directory.

Copied in rather than referenced where they lie. A requirements document the
user drags in from a Downloads folder should not stop working because they
tidied up, and the copy is what gets named to the agent.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from tech_planner.application.ports.context_repository import ContextFile


class ContextFileExists(FileExistsError):
    """A document of that name is already attached."""


@dataclass(frozen=True, slots=True)
class FileContextRepository:
    root: Path = Path("context")

    def list(self) -> tuple[ContextFile, ...]:
        if not self.root.is_dir():
            return ()
        return tuple(
            ContextFile(name=path.name, path=path.resolve(), size_bytes=path.stat().st_size)
            for path in sorted(self.root.iterdir())
            if path.is_file() and not path.name.startswith(".")
        )

    def add(self, source: Path, *, name: str | None = None) -> ContextFile:
        self.root.mkdir(parents=True, exist_ok=True)
        # `Path(...).name` on the caller's string, so a name like
        # "../../etc/passwd" cannot escape the context directory.
        target = self.root / Path(name or source.name).name
        if target.exists():
            raise ContextFileExists(f"{target.name} is already attached")
        shutil.copy2(source, target)
        return ContextFile(
            name=target.name, path=target.resolve(), size_bytes=target.stat().st_size
        )

    def remove(self, name: str) -> None:
        (self.root / Path(name).name).unlink(missing_ok=True)
