"""Domain-level errors.

These signal a violated invariant — a value or structure that must never exist.
Rule *findings* that the user should see and decide about are not errors; they
are `RuleViolation`s (see `domain.rules`).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every domain invariant breach."""


class InvalidEstimate(DomainError):
    """An estimate that cannot describe real work (zero, negative, absurd)."""


class InvalidHierarchy(DomainError):
    """The work-item tree is malformed: orphans, cycles, or illegal nesting."""


class DuplicateReference(DomainError):
    """Two work items claim the same reference."""


class InvalidTransition(DomainError):
    """A planning session was asked to do something its state does not allow.

    This is the approval gate expressed in the domain: creating without a prior
    approval, or approving a plan that breaks a mandatory rule, is not a
    workflow mistake to warn about — it is a state that must not exist.
    """
