"""Planning sessions, as one JSON file each.

JSON files rather than a database, because the amount of state involved is
genuinely small and this keeps it inspectable: when a run goes wrong, the record
of what was proposed and approved can be read with `cat`.

The proposal is stored in the same shape the agent produces it, so reading it
back goes through the same parser. That keeps one mapping correct instead of
two, and means a session reloaded from disk has been through exactly the same
domain invariants as one straight off the wire.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from tech_planner.adapters.driven.claude_code.dto import dump_proposal, parse_proposal
from tech_planner.application.ports.session_repository import SessionNotFound
from tech_planner.domain.model.approval import ApprovalDecision, CreatedItem
from tech_planner.domain.model.estimate import DEFAULT_BUFFER_FACTOR
from tech_planner.domain.model.planning_session import PlanningSession, SessionStatus
from tech_planner.domain.model.scope import DEFAULT_SCOPE, PlanningScope
from tech_planner.domain.rules.violations import (
    RuleId,
    RuleViolation,
    Severity,
    ValidationReport,
)


@dataclass(frozen=True, slots=True)
class JsonSessionRepository:
    root: Path = Path(".tech-planner/sessions")

    def save(self, session: PlanningSession) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(session.id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(_dump(session), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temporary.replace(path)

    def get(self, session_id: str) -> PlanningSession:
        path = self._path(session_id)
        if not path.is_file():
            raise SessionNotFound(session_id)
        return _load(json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal))

    def list(self) -> tuple[PlanningSession, ...]:
        if not self.root.is_dir():
            return ()
        paths = sorted(
            self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        sessions = []
        for path in paths:
            try:
                sessions.append(
                    _load(json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal))
                )
            except (ValueError, KeyError):
                # One unreadable file must not make `sessions` unusable.
                continue
        return tuple(sessions)

    def _path(self, session_id: str) -> Path:
        # `Path(...).name` so a crafted id cannot address anything outside root.
        return self.root / f"{Path(session_id).name}.json"


def _dump(session: PlanningSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "saved_at": datetime.now(UTC).isoformat(),
        "requirement": session.requirement,
        "prompt_revision": session.prompt_revision,
        "status": str(session.status),
        "scope": str(session.scope),
        "buffer_factor": str(session.buffer_factor),
        "capacity_hours": (
            str(session.capacity_hours) if session.capacity_hours is not None else None
        ),
        "proposal": dump_proposal(session.proposal) if session.proposal else None,
        "report": _dump_report(session.report),
        "decision": _dump_decision(session.decision),
        "created": [
            {"ref": c.ref, "backend_id": c.backend_id, "url": c.url} for c in session.created
        ],
        "failure": session.failure,
    }


def _load(data: Any) -> PlanningSession:
    # Re-buffered with the factor this plan was proposed under, never today's.
    buffer_factor = Decimal(str(data.get("buffer_factor", DEFAULT_BUFFER_FACTOR)))
    proposal = (
        parse_proposal(data["proposal"], buffer_factor=buffer_factor).proposal
        if data.get("proposal")
        else None
    )
    capacity = data.get("capacity_hours")
    return PlanningSession(
        id=data["id"],
        requirement=data.get("requirement", ""),
        prompt_revision=data.get("prompt_revision"),
        scope=PlanningScope.parse(data["scope"]) if data.get("scope") else DEFAULT_SCOPE,
        buffer_factor=buffer_factor,
        capacity_hours=Decimal(str(capacity)) if capacity is not None else None,
        status=SessionStatus(data.get("status", SessionStatus.DRAFTING)),
        proposal=proposal,
        report=_load_report(data.get("report")),
        decision=_load_decision(data.get("decision")),
        created=tuple(
            CreatedItem(ref=c["ref"], backend_id=c["backend_id"], url=c.get("url"))
            for c in data.get("created", [])
        ),
        failure=data.get("failure"),
    )


def _dump_report(report: ValidationReport | None) -> Any:
    if report is None:
        return None
    return [
        {
            "rule": str(v.rule),
            "severity": str(v.severity),
            "message": v.message,
            "item_ref": v.item_ref,
        }
        for v in report.violations
    ]


def _load_report(raw: Any) -> ValidationReport | None:
    if raw is None:
        return None
    return ValidationReport(
        violations=tuple(
            RuleViolation(
                rule=RuleId(v["rule"]),
                severity=Severity(v["severity"]),
                message=v["message"],
                item_ref=v.get("item_ref"),
            )
            for v in raw
        )
    )


def _dump_decision(decision: ApprovalDecision | None) -> Any:
    if decision is None:
        return None
    return {
        "approved": decision.approved,
        "decided_at": decision.decided_at.isoformat(),
        "note": decision.note,
    }


def _load_decision(raw: Any) -> ApprovalDecision | None:
    if raw is None:
        return None
    return ApprovalDecision(
        approved=raw["approved"],
        decided_at=datetime.fromisoformat(raw["decided_at"]),
        note=raw.get("note", ""),
    )
