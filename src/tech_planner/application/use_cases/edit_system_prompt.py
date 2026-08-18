"""Read and replace the system prompt — the spec's "System prompt editor".

Thin by design. The prompt is a first-class, always-editable input, not a
setting buried behind validation: the user is allowed to write whatever they
want in it, including something that plans badly. The only thing worth doing
here beyond the read and the write is refusing to save an empty prompt, since
that would leave the agent with no instructions at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from tech_planner.application.ports.prompt_repository import PromptRepository


class EmptyPrompt(ValueError):
    """Saving a blank system prompt would leave the agent uninstructed."""


@dataclass(frozen=True, slots=True)
class EditSystemPrompt:
    prompts: PromptRepository

    def read(self) -> str:
        return self.prompts.read_editable()

    def write(self, text: str) -> None:
        if not text.strip():
            raise EmptyPrompt("the system prompt must not be empty")
        self.prompts.write_editable(text)

    def preview_assembled(self) -> str:
        """What the agent will actually receive: the text plus the backend adapter."""
        return self.prompts.assemble().text
