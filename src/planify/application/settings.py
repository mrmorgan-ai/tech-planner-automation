"""Configuration, in the application's own vocabulary.

Note what the backend section is *not*: there are no `organization` or
`project` fields here. Those are Azure Boards' words, and the core does not
speak them. A backend is a name plus an opaque bag of options, which the prompt
adapter document interpolates. Adding Jira later means a new adapter document
and different keys in the bag — no change to this file, and none to the
planning rules. That is the spec's ports-and-adapters intent, honoured at the
one place it actually costs something to honour.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from planify.domain.model.estimate import DEFAULT_BUFFER_FACTOR
from planify.domain.model.scope import PlanningCadence, PlanningScope
from planify.domain.model.sprint import DEFAULT_STORY_CAPACITY_HOURS, SprintCapacity
from planify.domain.rules.definition_of_done import DefinitionOfDone
from planify.domain.rules.planning_rules import PlanningPolicy


class ToolProfile(StrEnum):
    """How much of the user's environment a run may reach.

    OPEN is the default and is what the spec asks for: the tool inherits the
    user's whole Claude Code environment — MCP servers, plugins, skills — and
    the propose pass is gated by *denying* the backend's mutating tools.

    STRICT trades that away for an exhaustive allow-list. The difference is
    real and worth stating plainly: under OPEN, creating work items in the
    configured backend is impossible during a propose pass, but some other
    connector the user has installed could still write somewhere else. STRICT
    exists for when that is unacceptable.
    """

    OPEN = "open"
    STRICT = "strict"


@dataclass(frozen=True, slots=True)
class BackendSettings:
    """Which work-tracking backend is enabled, and its adapter's parameters."""

    name: str = "azure-boards"
    #: Interpolated into the adapter prompt document. Opaque to the core.
    options: Mapping[str, str] = field(default_factory=dict)
    #: Path to an MCP configuration providing the backend's tools.
    mcp_config: Path | None = None


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """How the agent runtime is invoked."""

    #: Resolved on PATH. Never an API key — the tool runs the user's own
    #: authenticated installation and never sees a credential.
    binary: str = "claude"
    model: str | None = None
    #: Repositories the agent may read to ground its estimates. These are
    #: exposed for reading only; their own instruction files are not loaded.
    add_dirs: tuple[Path, ...] = ()
    tool_profile: ToolProfile = ToolProfile.OPEN
    #: Extra tool names to permit on top of the profile, for a user whose
    #: environment needs something the profile does not anticipate.
    extra_allowed_tools: tuple[str, ...] = ()
    #: Extra tool names to deny in both passes. This is the escape hatch for
    #: the OPEN profile's known limit: if an installed MCP server exposes its
    #: own shell or HTTP capability, name it here.
    extra_denied_tools: tuple[str, ...] = ()
    #: Clean working directory for the subprocess, kept away from this repo so
    #: no project-scoped configuration is discovered.
    workspace: Path = Path("workspace")


@dataclass(frozen=True, slots=True)
class Settings:
    backend: BackendSettings = BackendSettings()
    agent: AgentSettings = AgentSettings()
    #: Buffered hours one User Story may carry and still fit a sprint. Only the
    #: team knows this number, so it is configuration rather than a constant.
    #: This is the *fallback*: a value recorded for a specific sprint wins.
    story_capacity_hours: Decimal = DEFAULT_STORY_CAPACITY_HOURS
    #: Contingency multiplier on every hour estimate. The spec fixes it at 1.30;
    #: teams adjust it as they learn what their contingency really costs.
    buffer_factor: Decimal = DEFAULT_BUFFER_FACTOR
    #: Which planning event runs by default. Annual plans Epics into Features,
    #: quarterly plans Features into User Stories, sprint plans stories into
    #: tasks — and each cadence decides which rules even apply.
    cadence: PlanningCadence = PlanningCadence.SPRINT
    require_acceptance_criteria: bool = True

    def planning_policy(
        self,
        *,
        scope: PlanningScope | None = None,
        capacity_hours: Decimal | None = None,
    ) -> PlanningPolicy:
        """The domain policy these settings describe.

        Both overrides exist because they change per run rather than per team:
        the cadence is whichever planning event you are in, and capacity is
        whatever this particular sprint has. Neither belongs in a config file
        you would have to edit four times a month.
        """
        return PlanningPolicy(
            scope=scope or PlanningScope.for_cadence(self.cadence),
            capacity=SprintCapacity(
                story_capacity_hours=capacity_hours
                if capacity_hours is not None
                else self.story_capacity_hours
            ),
            definition_of_done=DefinitionOfDone(),
            require_acceptance_criteria=self.require_acceptance_criteria,
        )
