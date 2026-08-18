"""The Definition of Done, as a checkable set rather than a paragraph.

The spec: a User Story is not done because development finished. It must be
implemented, tested in the relevant environments, deployed according to scope,
and documented — with explicit Tasks for each.

It also says "when applicable", which is doing real work in that sentence. A
spike produces no deployment; a copy change needs no production validation. So
the requirement is expressed as a *policy* the caller configures, not a fixed
list, and the default is the spec's full set.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from planify.domain.model.work_item import TaskKind

#: The full Definition of Done from the spec.
FULL_DOD: frozenset[TaskKind] = frozenset(
    {
        TaskKind.IMPLEMENTATION,
        TaskKind.TECHNICAL_TESTING,
        TaskKind.FUNCTIONAL_TESTING,
        TaskKind.DEPLOY_TESTING,
        TaskKind.VALIDATE_TESTING,
        TaskKind.DEPLOY_PRODUCTION,
        TaskKind.VALIDATE_PRODUCTION,
        TaskKind.DOCUMENTATION,
    }
)

#: A reduced set for work that genuinely ships nothing (spikes, research).
INVESTIGATION_DOD: frozenset[TaskKind] = frozenset(
    {TaskKind.ANALYSIS, TaskKind.DOCUMENTATION}
)

#: Tag a story with this to opt it out of the deployment-related requirements.
NO_DEPLOYMENT_TAG = "no-deployment"

_DEPLOYMENT_KINDS: frozenset[TaskKind] = frozenset(
    {
        TaskKind.DEPLOY_TESTING,
        TaskKind.VALIDATE_TESTING,
        TaskKind.DEPLOY_PRODUCTION,
        TaskKind.VALIDATE_PRODUCTION,
    }
)


@dataclass(frozen=True, slots=True)
class DefinitionOfDone:
    """Which task kinds a story must cover to be considered plannable."""

    required: frozenset[TaskKind] = field(default=FULL_DOD)

    def without_deployment(self) -> DefinitionOfDone:
        return DefinitionOfDone(required=self.required - _DEPLOYMENT_KINDS)

    def missing_from(self, present: frozenset[TaskKind]) -> frozenset[TaskKind]:
        return self.required - present

    def applies_to_tags(self, tags: tuple[str, ...]) -> DefinitionOfDone:
        """Narrow the requirement based on a story's own tags."""
        if NO_DEPLOYMENT_TAG in tags:
            return self.without_deployment()
        return self
