"""The composition root: the one place that knows every concrete class.

Everything else depends on ports. This module is where the arrows finally point
at real implementations, so swapping the agent runtime, the storage format, or
the settings source is an edit here and nowhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from planify.adapters.driven.claude_code.gateway import ClaudeCodeGateway
from planify.adapters.driven.config.py_settings import (
    DEFAULT_PATH,
    PySettingsProvider,
)
from planify.adapters.driven.filesystem.context_repository import FileContextRepository
from planify.adapters.driven.filesystem.prompt_repository import FilePromptRepository
from planify.adapters.driven.persistence.capacity_repository import (
    JsonCapacityRepository,
)
from planify.adapters.driven.persistence.session_repository import JsonSessionRepository
from planify.application.ports.agent_gateway import AgentGateway
from planify.application.settings import Settings
from planify.application.use_cases.approve_and_create import ApproveAndCreate
from planify.application.use_cases.converse_plan import ConversePlan
from planify.application.use_cases.edit_system_prompt import EditSystemPrompt
from planify.application.use_cases.manage_context_files import ManageContextFiles
from planify.application.use_cases.propose_plan import ProposePlan
from planify.application.use_cases.start_planning_session import StartPlanningSession


#: Re-exported so driving adapters need not reach into a driven adapter for it.
__all__ = [
    "Application",
    "DEFAULT_PATH",
    "build",
    "capacity_repository",
    "sessions_repository",
]


@dataclass(frozen=True, slots=True)
class Application:
    """Every use case, wired and ready."""

    settings: Settings
    #: The agent port itself. Exposed only so a health check can preflight the
    #: runtime without opening a session it would then have to throw away.
    agent: AgentGateway
    start_session: StartPlanningSession
    propose: ProposePlan
    #: Planning as a multi-turn session. `propose` remains for the CLI, which
    #: asks once and prints once; the web app opens one of these instead.
    converse: ConversePlan
    approve: ApproveAndCreate
    prompt: EditSystemPrompt
    context: ManageContextFiles
    capacity: JsonCapacityRepository


def build(config_path: Path = DEFAULT_PATH) -> Application:
    settings_provider = PySettingsProvider(path=config_path)
    # Loaded once here so a broken configuration fails at startup with one
    # clear message, rather than midway through a planning run.
    settings = settings_provider.load()

    gateway = ClaudeCodeGateway(settings=settings_provider)
    sessions = JsonSessionRepository()
    prompts = FilePromptRepository(backend=settings.backend)
    context = FileContextRepository()

    return Application(
        settings=settings,
        agent=gateway,
        start_session=StartPlanningSession(agent=gateway, sessions=sessions),
        propose=ProposePlan(
            agent=gateway,
            sessions=sessions,
            prompts=prompts,
            context=context,
            settings=settings_provider,
        ),
        converse=ConversePlan(
            agent=gateway,
            sessions=sessions,
            prompts=prompts,
            context=context,
            settings=settings_provider,
        ),
        approve=ApproveAndCreate(agent=gateway, sessions=sessions, prompts=prompts),
        prompt=EditSystemPrompt(prompts=prompts),
        context=ManageContextFiles(context=context),
        capacity=JsonCapacityRepository(),
    )


def sessions_repository() -> JsonSessionRepository:
    """For read-only commands that need no agent runtime and no configuration."""
    return JsonSessionRepository()


def capacity_repository() -> JsonCapacityRepository:
    """Capacity is edited far more often than it is planned with, so the
    commands that manage it deliberately need neither config nor a runtime."""
    return JsonCapacityRepository()
