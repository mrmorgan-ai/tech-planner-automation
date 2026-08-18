"""Per-sprint capacity, stored as one small JSON file.

Hours are written as strings so a round trip cannot turn an exact 64 into a
binary float, matching how every other number in this system is handled.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True, slots=True)
class JsonCapacityRepository:
    path: Path = Path(".planify/capacity.json")

    def get(self, sprint: str) -> Decimal | None:
        return self._load().get(sprint)

    def set(self, sprint: str, hours: Decimal) -> None:
        recorded = dict(self._load())
        recorded[sprint] = hours
        self._save(recorded)

    def clear(self, sprint: str) -> None:
        recorded = dict(self._load())
        if recorded.pop(sprint, None) is not None:
            self._save(recorded)

    def all(self) -> Mapping[str, Decimal]:
        return self._load()

    def _load(self) -> dict[str, Decimal]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt capacity file must not stop planning. Falling back to
            # the configured default is a worse estimate, not a broken tool.
            return {}
        recorded: dict[str, Decimal] = {}
        for sprint, hours in raw.items() if isinstance(raw, dict) else ():
            try:
                recorded[str(sprint)] = Decimal(str(hours))
            except InvalidOperation:
                continue
        return recorded

    def _save(self, recorded: Mapping[str, Decimal]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {sprint: str(hours) for sprint, hours in sorted(recorded.items())}
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
