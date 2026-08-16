"""Open a planning session, after checking the ground it stands on."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from tech_planner.application.ports.agent_gateway import AgentGateway
from tech_planner.application.ports.session_repository import SessionRepository
from tech_planner.domain.model.planning_session import PlanningSession
from tech_planner.domain.model.scope import PlanningScope


@dataclass(frozen=True, slots=True)
class SessionStarted:
    session: PlanningSession
    #: MCP servers the runtime reached. Reported so the user can see that the
    #: backend is present *and* that their own connectors came along with it.
    mcp_servers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StartPlanningSession:
    agent: AgentGateway
    sessions: SessionRepository

    async def __call__(
        self,
        requirement: str = "",
        *,
        scope: PlanningScope | None = None,
        buffer_factor: Decimal | None = None,
        capacity_hours: Decimal | None = None,
    ) -> SessionStarted:
        # Preflight first, and let it raise. A session whose backend is
        # unreachable will produce a plausible-looking plan built on invented
        # iteration paths — much worse than refusing to start.
        servers = await self.agent.preflight()
        session = PlanningSession(requirement=requirement)
        # Stamped on the session at the moment it opens, so the plan stays
        # reproducible if any of them is changed while it is awaiting approval.
        if scope is not None:
            session.scope = scope
        if buffer_factor is not None:
            session.buffer_factor = buffer_factor
        session.capacity_hours = capacity_hours
        self.sessions.save(session)
        return SessionStarted(session=session, mcp_servers=servers)
