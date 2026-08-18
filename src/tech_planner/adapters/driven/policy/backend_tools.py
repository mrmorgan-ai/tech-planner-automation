"""Which tools each work-tracking backend exposes, split by whether they write.

This is the one place that knows a backend's tool names. The planning core does
not, and must not: it asks for a PROPOSE or a CREATE pass and this module works
out what that means for the command line.

Adding a backend means adding an entry here plus a prompt adapter document.

.. warning::
   **These names must be verified against a live server, never assumed.**

   An earlier version of this file used the tool names from the Azure DevOps
   MCP documentation — ``wit_create_work_item``, ``wit_add_child_work_items``
   and so on. Not one of them exists on the server as it actually ships: it has
   consolidated into action-dispatched tools, so the real create tool is
   ``wit_work_item_write`` taking an action argument.

   The consequence was not a crash. A deny-list naming tools that do not exist
   denies nothing, and the propose pass would have run with full write access
   while reporting a gate that looked correct. Nothing in the code could notice
   — which is why `AgentGateway.preflight` now checks these names against the
   tools the runtime actually advertises, and refuses to start if any is
   missing. A rename in a future release becomes a startup error rather than a
   silently open gate.

   Recorded from a live ``system/init`` on 2026-08-15.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BackendTools:
    """A backend's MCP surface, as tool-name fragments."""

    #: MCP server name as registered in the MCP configuration. The runtime
    #: namespaces tools as ``mcp__<server>__<tool>``.
    server: str
    #: Tools that change the state of the backend. Denied during a propose
    #: pass, permitted only during a create pass.
    mutating: tuple[str, ...]
    #: Tools that only read. Needed in both passes — resolving a real iteration
    #: path before proposing a sprint is what stops us inventing one.
    reading: tuple[str, ...]

    def qualify(self, names: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(f"mcp__{self.server}__{name}" for name in names)

    @property
    def qualified_mutating(self) -> tuple[str, ...]:
        return self.qualify(self.mutating)

    @property
    def qualified_reading(self) -> tuple[str, ...]:
        return self.qualify(self.reading)


AZURE_BOARDS = BackendTools(
    server="azure-devops",
    # The server names every mutating tool with a `_write` suffix, which makes
    # this list easy to keep honest: anything ending in `_write` belongs here.
    # `wit_work_item_attachment` does not follow the convention but uploads, so
    # it is treated as mutating.
    mutating=(
        "wit_work_item_write",
        "wit_work_item_link_write",
        "wit_work_item_comment_write",
        "wit_work_item_attachment",
        "work_iteration_write",
        "work_capacity_write",
    ),
    reading=(
        "wit_work_item",
        "wit_query",
        "wit_backlog",
        "work",
        "core_list_projects",
        "core_list_project_teams",
        "core_get_identity_ids",
    ),
)

#: Registry keyed by the backend name in settings.
BACKENDS: dict[str, BackendTools] = {
    "azure-boards": AZURE_BOARDS,
}


class UnknownBackend(KeyError):
    """Settings name a backend that has no adapter."""


def tools_for(backend_name: str) -> BackendTools:
    try:
        return BACKENDS[backend_name]
    except KeyError:
        raise UnknownBackend(
            f"no adapter for backend {backend_name!r}; known backends: "
            + ", ".join(sorted(BACKENDS))
        ) from None
