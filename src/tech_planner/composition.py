"""The composition root: the one place that knows every concrete class.

Everything else depends on ports. This module is where the arrows finally point
at real implementations, so swapping the agent runtime, the storage format, or
the settings source is an edit here and nowhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tech_planner.adapters.driven.claude_code.gateway import ClaudeCodeGateway
from tech_planner.adapters.driven.config.py_settings import (
    DEFAULT_PATH,
    PySettingsProvider,
)
from tech_planner.adapters.driven.filesystem.context_repository import FileContextRepository
from tech_planner.adapters.driven.filesystem.prompt_repository import FilePromptRepository
from tech_planner.adapters.driven.persistence.session_repository import JsonSessionRepository
from tech_planner.application.settings import Settings
from tech_planner.application.use_cases.approve_and_create import ApproveAndCreate
from tech_planner.application.use_cases.edit_system_prompt import EditSystemPrompt
from tech_planner.application.use_cases.manage_context_files import ManageContextFiles
from tech_planner.application.use_cases.propose_plan import ProposePlan
from tech_planner.application.use_cases.start_planning_session import StartPlanningSession


#: Re-exported so driving adapters need not reach into a driven adapter for it.
__all__ = ["Application", "DEFAULT_PATH", "build", "sessions_repository"]


@dataclass(frozen=True, slots=True)
class Application:
    """Every use case, wired and ready."""

    settings: Settings
    start_session: StartPlanningSession
    propose: ProposePlan
    approve: ApproveAndCreate
    prompt: EditSystemPrompt
    context: ManageContextFiles


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
        start_session=StartPlanningSession(agent=gateway, sessions=sessions),
        propose=ProposePlan(
            agent=gateway,
            sessions=sessions,
            prompts=prompts,
            context=context,
            settings=settings_provider,
        ),
        approve=ApproveAndCreate(agent=gateway, sessions=sessions, prompts=prompts),
        prompt=EditSystemPrompt(prompts=prompts),
        context=ManageContextFiles(context=context),
    )


def sessions_repository() -> JsonSessionRepository:
    """For read-only commands that need no agent runtime and no configuration."""
    return JsonSessionRepository()
