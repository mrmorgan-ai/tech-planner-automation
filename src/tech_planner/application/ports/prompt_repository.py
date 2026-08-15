"""Where the system prompt comes from, and how the user edits it.

Two things are distinguished on purpose:

* the **editable** prompt — `prompts/system.md`, the role and planning rules,
  which the UI exposes as a plain textarea;
* the **assembled** prompt — that text plus the enabled backend adapter's
  section, which is what the agent actually receives.

The user edits the first and never has to think about the second. Adding a
backend later means adding an adapter document, not changing this port.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SystemPrompt:
    """The full instruction set for a run, with an identity."""

    text: str
    #: Content digest. Recorded on the session so that editing the prompt
    #: mid-conversation is visible rather than silent.
    revision: str

    def __len__(self) -> int:
        return len(self.text)


@runtime_checkable
class PromptRepository(Protocol):
    def read_editable(self) -> str:
        """The user-owned prompt text, exactly as it sits on disk."""
        ...

    def write_editable(self, text: str) -> None:
        """Replace it. Takes effect on the next turn, not the one in flight."""
        ...

    def assemble(self) -> SystemPrompt:
        """The editable text plus the enabled backend adapter's instructions."""
        ...
