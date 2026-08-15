"""Open a planning session, after checking the ground it stands on."""

from __future__ import annotations

from dataclasses import dataclass

from tech_planner.application.ports.agent_gateway import AgentGateway
from tech_planner.application.ports.session_repository import SessionRepository
from tech_planner.domain.model.planning_session import PlanningSession


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

    async def __call__(self, requirement: str = "") -> SessionStarted:
        # Preflight first, and let it raise. A session whose backend is
        # unreachable will produce a plausible-looking plan built on invented
        # iteration paths — much worse than refusing to start.
        servers = await self.agent.preflight()
        session = PlanningSession(requirement=requirement)
        self.sessions.save(session)
        return SessionStarted(session=session, mcp_servers=servers)
