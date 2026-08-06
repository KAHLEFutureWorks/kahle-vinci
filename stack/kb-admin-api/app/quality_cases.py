from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

try:
    from .portal_governance import SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import SQLiteGovernanceStore


RAG_REASONS = {
    "incorrect", "outdated", "conflicting_sources", "irrelevant_source",
    "suspected_permission_issue", "other",
}


class QualityCaseError(ValueError):
    pass


class QualityCaseService:
    def __init__(self, store: SQLiteGovernanceStore, *, identifier: Callable[[], str] | None = None,
                 now: Callable[[], str] | None = None):
        self.store = store
        self.identifier = identifier or (lambda: str(uuid.uuid4()))
        self.now = now or (lambda: datetime.now().astimezone().isoformat())
        self._initialize()

    def _initialize(self) -> None:
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS system_incidents (
                    incident_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                    step TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
                    diagnostic_json TEXT NOT NULL, user_comment TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rag_feedback (
                    feedback_id TEXT PRIMARY KEY, reported_by_user_id TEXT NOT NULL,
                    reason TEXT NOT NULL, comment TEXT NOT NULL, question TEXT NOT NULL,
                    answer TEXT NOT NULL, sources_json TEXT NOT NULL, passages_json TEXT NOT NULL,
                    rights_json TEXT NOT NULL, runtime_json TEXT NOT NULL, request_id TEXT NOT NULL,
                    severity TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    resolved_at TEXT, resolution_reason TEXT
                );
            """)

    def system_incident(self, step: str, diagnostic: dict[str, Any], *, fingerprint: str | None = None) -> str:
        safe_diagnostic = {key: value for key, value in diagnostic.items() if key not in {"content", "document", "answer"}}
        fingerprint = fingerprint or hashlib.sha256(
            f"{step}|{json.dumps(safe_diagnostic, sort_keys=True)}".encode("utf-8")
        ).hexdigest()
        stamp = self.now()
        with self.store.connect() as db:
            existing = db.execute("SELECT incident_id FROM system_incidents WHERE fingerprint = ?", (fingerprint,)).fetchone()
            if existing:
                return existing["incident_id"]
            incident_id = self.identifier()
            db.execute(
                "INSERT INTO system_incidents VALUES (?, ?, ?, 'critical', 'open', ?, NULL, ?, ?)",
                (incident_id, fingerprint, step, json.dumps(safe_diagnostic, sort_keys=True), stamp, stamp),
            )
        return incident_id

    def add_incident_comment(self, incident_id: str, comment: str) -> None:
        if len(comment.strip()) < 3:
            raise QualityCaseError("incident_comment_required")
        with self.store.connect() as db:
            cursor = db.execute(
                "UPDATE system_incidents SET user_comment = ?, updated_at = ? WHERE incident_id = ?",
                (comment.strip()[:2000], self.now(), incident_id),
            )
            if not cursor.rowcount:
                raise QualityCaseError("unknown_incident")

    def report_rag(self, *, user_id: str, reason: str, comment: str, question: str, answer: str,
                   sources: list[dict[str, Any]], passages: list[dict[str, Any]], rights: list[str],
                   runtime: dict[str, Any], request_id: str) -> str:
        if reason not in RAG_REASONS:
            raise QualityCaseError("invalid_feedback_reason")
        feedback_id = self.identifier(); stamp = self.now()
        severity = "critical" if reason == "suspected_permission_issue" else "normal"
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO rag_feedback VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, NULL, NULL)",
                (feedback_id, user_id, reason, comment.strip()[:2000], question[:8000], answer[:16000],
                 json.dumps(sources), json.dumps(passages), json.dumps(rights), json.dumps(runtime),
                 request_id[:200], severity, stamp),
            )
        return feedback_id

    def open_cases(self) -> dict[str, list[dict[str, Any]]]:
        with self.store.connect() as db:
            incidents = [dict(row) for row in db.execute(
                "SELECT * FROM system_incidents WHERE status = 'open' ORDER BY created_at DESC"
            ).fetchall()]
            feedback = [dict(row) for row in db.execute(
                "SELECT * FROM rag_feedback WHERE status = 'open' ORDER BY created_at DESC"
            ).fetchall()]
        return {"incidents": incidents, "feedback": feedback}
