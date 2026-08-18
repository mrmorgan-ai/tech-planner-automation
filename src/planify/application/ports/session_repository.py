"""Persistence for planning sessions.

Scoped tightly on purpose. We are the system of record for almost nothing: the
agent runtime owns the conversation transcript and the work-tracking backend
owns the work items. What is ours is the thin band in between — which
requirement we were planning, what was proposed, what the rules said, whether
the user approved, and what came back.

That is also why there is no repository per entity. `PlanningSession` is the
only aggregate with a life cycle, so it is the only one with a repository.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from planify.domain.model.planning_session import PlanningSession


class SessionNotFound(LookupError):
    """No session with that id has been recorded."""


@runtime_checkable
class SessionRepository(Protocol):
    def save(self, session: PlanningSession) -> None:
        """Persist the session's current state, creating or replacing it."""
        ...

    def get(self, session_id: str) -> PlanningSession:
        """Raise :class:`SessionNotFound` if it is not there."""
        ...

    def list(self) -> tuple[PlanningSession, ...]:
        """Most recently touched first."""
        ...
