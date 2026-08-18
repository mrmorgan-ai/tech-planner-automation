"""The system prompt, assembled from Markdown on disk.

The split is the point. `prompts/system.md` holds the role and the planning
rules and is what the UI's prompt editor opens; `prompts/adapters/<backend>.md`
holds everything tool-specific and is chosen by configuration. Supporting a new
work-tracking backend is then a new Markdown file — no Python, and no change to
the planning rules, which is exactly the separation the spec's ports-and-adapters
section asks for.

The assembled prompt **replaces** the runtime's default rather than adding to
it, so what the user reads in the editor is the whole of what the model is told.
That has a cost worth stating: none of the runtime's default guidance about how
to use tools comes along, so `system.md` carries its own.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from planify.application.ports.prompt_repository import SystemPrompt
from planify.application.settings import BackendSettings

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


class PromptNotFound(FileNotFoundError):
    """The prompt files are missing from the installation."""


@dataclass(frozen=True, slots=True)
class FilePromptRepository:
    backend: BackendSettings
    root: Path = Path("prompts")

    @property
    def editable_path(self) -> Path:
        return self.root / "system.md"

    @property
    def adapter_path(self) -> Path:
        return self.root / "adapters" / f"{self.backend.name}.md"

    def read_editable(self) -> str:
        try:
            return self.editable_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise PromptNotFound(
                f"no system prompt at {self.editable_path}"
            ) from None

    def write_editable(self, text: str) -> None:
        self.editable_path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a half-written prompt is worse than an old one,
        # and the UI saves this on every keystroke pause.
        temporary = self.editable_path.with_suffix(".md.tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(self.editable_path)

    def assemble(self) -> SystemPrompt:
        parts = [self.read_editable().rstrip()]
        if self.adapter_path.is_file():
            parts.append(_fill(self.adapter_path.read_text(encoding="utf-8"), self.backend))
        text = "\n\n".join(parts) + "\n"
        return SystemPrompt(text=text, revision=_revision(text))


def unfilled_placeholders(text: str) -> tuple[str, ...]:
    """Placeholder names still present in an assembled prompt.

    Uses the same pattern as the substitution, so prose that merely mentions
    the `{{ }}` syntax — as the adapter documents do when explaining
    themselves — is not mistaken for a configuration gap.
    """
    return tuple(dict.fromkeys(_PLACEHOLDER.findall(text)))


def _fill(template: str, backend: BackendSettings) -> str:
    """Substitute `{{ key }}` from the backend's options.

    An unknown placeholder is left visible rather than blanked. A prompt saying
    `{{organization}}` tells the user their configuration is incomplete; one
    silently saying nothing produces a confidently wrong plan.
    """
    return _PLACEHOLDER.sub(
        lambda match: backend.options.get(match.group(1), match.group(0)), template
    )


def _revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
