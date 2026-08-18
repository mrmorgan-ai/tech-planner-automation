"""Copy to config/settings.py and fill in. The real file is gitignored.

Define a module-level `settings`, or a `build()` that returns one. This file is
executed at startup, so anything you can compute in Python is available — but
that also means whatever is in here runs with your privileges.

Planning runs on your Claude Code subscription — the tool drives your own
signed-in installation, so the only credentials that ever appear are your
backend's, and those live in the environment rather than in this file. Run
`claude auth` if you are not signed in.
"""

from decimal import Decimal
from pathlib import Path

from tech_planner.application.settings import (
    AgentSettings,
    BackendSettings,
    Settings,
    ToolProfile,
)
from tech_planner.domain.model.scope import PlanningCadence

settings = Settings(
    backend=BackendSettings(
        # The only implemented backend today. The name selects both the tool
        # mapping and the prompt adapter at prompts/adapters/<name>.md.
        name="azure-boards",
        # Provides the backend's tools. Added on top of your own MCP servers,
        # not instead of them.
        mcp_config=Path(".mcp.json"),
        # Interpolated into the prompt adapter as {{ placeholders }}. These are
        # Azure Boards' terms; another backend would use its own.
        options={
            "organization": "<YOUR-ORG>",
            "project": "<YOUR-PROJECT>",
            # Decides the story-points field name:
            #   Agile -> Microsoft.VSTS.Scheduling.StoryPoints
            #   Scrum -> .Effort        CMMI -> .Size
            "process": "<Agile | Scrum | CMMI>",
            # Which part of the project new work items are filed under.
            #
            # Azure Boards has two orthogonal ways of slicing a project:
            # *iterations* answer "when" (Sprint 12), *areas* answer "who or
            # what" — a component, a team, a product line. Areas form a tree
            # rooted at the project name and are written with backslashes:
            #
            #   OrganizationControl                  <- project root
            #   OrganizationControl\Backend
            #   OrganizationControl\Backend\Payments
            #
            # Teams subscribe to areas, so the area path is what decides which
            # team's board a work item shows up on. Setting it wrong files
            # correct work where nobody is looking at it.
            #
            # Leave it empty to inherit the project root, which is the right
            # answer for a small project that has never subdivided. Find yours
            # under Project settings -> Project configuration -> Areas.
            "area_path": "",
        },
    ),
    agent=AgentSettings(
        # Resolved on PATH.
        binary="claude",
        # Model alias or full name. None uses your installation's default.
        model=None,
        # Repositories the agent may read to ground its estimates. Exposed for
        # reading only — their own CLAUDE.md files are never loaded as
        # instructions. Being Python, this can be computed:
        #     add_dirs=tuple(sorted(Path.home().glob("work/*/")))
        add_dirs=(),
        # OPEN   - inherit your whole environment (MCP servers, plugins, skills),
        #          with the backend's write tools and the exec/write family
        #          denied during planning. The default, and what the tool is for.
        #          Honest limit: an installed MCP server offering its own shell
        #          or HTTP capability could reach the backend's REST API another
        #          way. Name any such server in extra_denied_tools.
        # STRICT - an exhaustive allow-list instead: backend read tools,
        #          Read/Glob/Grep and nothing else. Creating anything during
        #          planning becomes impossible by construction, at the cost of
        #          your research tooling.
        tool_profile=ToolProfile.OPEN,
        extra_allowed_tools=(),
        extra_denied_tools=(),
        # Clean working directory for the subprocess, kept away from the
        # repository so no project-scoped configuration or hooks are found.
        workspace=Path("workspace"),
    ),
    # Which planning event runs when you do not name one with --cadence:
    #   ANNUAL     Epic      -> Feature     (sized in story points)
    #   QUARTERLY  Feature   -> UserStory   (sized in story points)
    #   SPRINT     UserStory -> Task        (sized in hours, buffered)
    # The cadence decides which rules even apply: the two-day task ceiling and
    # sprint capacity are statements about hours, and coarser plans have none.
    cadence=PlanningCadence.SPRINT,
    # Contingency multiplier on every hour estimate. The spec fixes it at 1.30;
    # change it as you learn what your contingency actually costs. Override for
    # one run with --buffer. Whatever is in force is recorded on the session, so
    # a plan approved at 1.30 still writes 1.30 after you change this.
    buffer_factor=Decimal("1.30"),
    # Buffered hours one User Story may carry and still fit a two-week sprint.
    # Only your team knows this: it is one person's availability minus ceremony,
    # support and slack. The default is 64 (ten days at 80%).
    #
    # This is the fallback. Capacity really changes every sprint, so record it
    # per sprint instead and leave this as the floor:
    #     tech-planner capacity "Sprint 13" 48
    story_capacity_hours=Decimal("64"),
    require_acceptance_criteria=True,
)


# The alternative shape, for configuration that has to be computed. Define this
# instead of `settings` and it wins:
#
# def build() -> Settings:
#     import socket
#     on_laptop = socket.gethostname().endswith(".local")
#     return Settings(
#         backend=BackendSettings(...),
#         agent=AgentSettings(
#             tool_profile=ToolProfile.OPEN if on_laptop else ToolProfile.STRICT,
#         ),
#     )
