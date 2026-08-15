"""Work items: Epic, Feature, User Story, Task.

These carry the spec's *canonical* fields, deliberately provider-agnostic. The
mapping to Azure Boards reference names (``System.Title``,
``Microsoft.VSTS.Scheduling.OriginalEstimate``, ...) is not done here and not
done in Python at all — it lives in the prompt adapter, because the agent is
what writes to the backend.

Items are flat: each carries a `parent_ref` rather than a list of children. The
agent returns them as a flat list (a shallow schema is markedly more reliable
than a deeply nested one), and `PlanProposal` reassembles the tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tech_planner.domain.errors import DomainError
from tech_planner.domain.model.effort import TaskEffort
from tech_planner.domain.model.sprint import Sprint


class WorkItemType(StrEnum):
    EPIC = "Epic"
    FEATURE = "Feature"
    USER_STORY = "UserStory"
    TASK = "Task"


class TaskKind(StrEnum):
    """What a Task is *for*.

    The Definition of Done is expressed in terms of these, so classifying tasks
    is what lets us check DoD coverage mechanically instead of by reading prose.
    """

    IMPLEMENTATION = "implementation"
    TECHNICAL_TESTING = "technical_testing"
    FUNCTIONAL_TESTING = "functional_testing"
    DEPLOY_TESTING = "deploy_testing"
    VALIDATE_TESTING = "validate_testing"
    DEPLOY_PRODUCTION = "deploy_production"
    VALIDATE_PRODUCTION = "validate_production"
    DOCUMENTATION = "documentation"
    #: Research / spike work. The spec requires these to be explicit rather
    #: than hidden inside the 30% buffer.
    ANALYSIS = "analysis"
    OTHER = "other"


#: Which parent type each item type may hang from. ``None`` means "may be a root".
ALLOWED_PARENT_TYPES: dict[WorkItemType, frozenset[WorkItemType | None]] = {
    WorkItemType.EPIC: frozenset({None}),
    WorkItemType.FEATURE: frozenset({WorkItemType.EPIC, None}),
    WorkItemType.USER_STORY: frozenset({WorkItemType.FEATURE, None}),
    WorkItemType.TASK: frozenset({WorkItemType.USER_STORY}),
}


@dataclass(frozen=True, kw_only=True)
class WorkItem:
    """Fields common to every item type."""

    #: Plan-local identifier used to express parentage. Not a backend id —
    #: nothing has been created yet when a proposal is validated.
    ref: str
    title: str
    description: str = ""
    parent_ref: str | None = None
    sprint: Sprint | None = None
    area: str | None = None
    assignee: str | None = None
    priority: int | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.ref.strip():
            raise DomainError("work item ref must not be blank")
        if not self.title.strip():
            raise DomainError(f"work item {self.ref!r} must have a title")
        if self.parent_ref is not None and self.parent_ref == self.ref:
            raise DomainError(f"work item {self.ref!r} cannot be its own parent")
        if self.priority is not None and not 1 <= self.priority <= 4:
            raise DomainError(
                f"work item {self.ref!r} has priority {self.priority}; expected 1-4"
            )

    @property
    def type(self) -> WorkItemType:  # pragma: no cover - overridden in every subclass
        raise NotImplementedError


@dataclass(frozen=True, kw_only=True)
class _Describable(WorkItem):
    """An item that carries acceptance criteria (everything except a Task)."""

    acceptance_criteria: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Epic(_Describable):
    @property
    def type(self) -> WorkItemType:
        return WorkItemType.EPIC


@dataclass(frozen=True, kw_only=True)
class Feature(_Describable):
    @property
    def type(self) -> WorkItemType:
        return WorkItemType.FEATURE


@dataclass(frozen=True, kw_only=True)
class UserStory(_Describable):
    """A story: the unit the sprint-fit rule applies to.

    Story Points live on the story and hours live on its Tasks — the spec is
    firm that the two are never mixed on the same item.
    """

    story_points: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.story_points is not None and self.story_points <= 0:
            raise DomainError(
                f"user story {self.ref!r} has non-positive story points: {self.story_points}"
            )

    @property
    def type(self) -> WorkItemType:
        return WorkItemType.USER_STORY


@dataclass(frozen=True, kw_only=True)
class Task(WorkItem):
    """Concrete executable work, sized in hours."""

    effort: TaskEffort
    kind: TaskKind = TaskKind.OTHER

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.parent_ref is None:
            raise DomainError(f"task {self.ref!r} must belong to a user story")

    @property
    def type(self) -> WorkItemType:
        return WorkItemType.TASK


AnyWorkItem = Epic | Feature | UserStory | Task
