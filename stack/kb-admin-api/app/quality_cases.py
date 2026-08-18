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
                    resolved_at TEXT, resolution_reason TEXT,
                    screenshot_filename TEXT, document_ids_json TEXT NOT NULL DEFAULT '[]',
                    knowledgebase_ids_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS feedback_attachments (
                    attachment_id TEXT PRIMARY KEY,
                    feedback_id TEXT NOT NULL REFERENCES rag_feedback(feedback_id),
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            # Bestehende Datenbanken kennen die Spalte noch nicht; CREATE TABLE
            # IF NOT EXISTS ergaenzt sie nicht nachtraeglich.
            columns = {row["name"] for row in db.execute("PRAGMA table_info(rag_feedback)")}
            if "screenshot_filename" not in columns:
                db.execute("ALTER TABLE rag_feedback ADD COLUMN screenshot_filename TEXT")
            if "document_ids_json" not in columns:
                db.execute("ALTER TABLE rag_feedback ADD COLUMN document_ids_json TEXT NOT NULL DEFAULT '[]'")
            if "knowledgebase_ids_json" not in columns:
                db.execute("ALTER TABLE rag_feedback ADD COLUMN knowledgebase_ids_json TEXT NOT NULL DEFAULT '[]'")

    def system_incident(self, step: str, diagnostic: dict[str, Any], *, fingerprint: str | None = None) -> str:
        safe_diagnostic = {key: value for key, value in diagnostic.items() if key not in {"content", "document", "answer"}}
        fingerprint = fingerprint or hashlib.sha256(
            f"{step}|{json.dumps(safe_diagnostic, sort_keys=True)}".encode("utf-8")
        ).hexdigest()
        stamp = self.now()
        with self.store.connect() as db:
            existing = db.execute(
                "SELECT incident_id, status FROM system_incidents WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            if existing:
                if existing["status"] != "open":
                    db.execute(
                        "UPDATE system_incidents SET status='open', diagnostic_json=?, user_comment=NULL, updated_at=? "
                        "WHERE incident_id=?",
                        (json.dumps(safe_diagnostic, sort_keys=True), stamp, existing["incident_id"]),
                    )
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
                   runtime: dict[str, Any], request_id: str,
                   document_ids: list[str] | None = None,
                   knowledgebase_ids: list[str] | None = None) -> str:
        if reason not in RAG_REASONS:
            raise QualityCaseError("invalid_feedback_reason")
        feedback_id = self.identifier(); stamp = self.now()
        severity = "critical" if reason == "suspected_permission_issue" else "normal"
        with self.store.connect() as db:
            db.execute(
                # Spalten ausdruecklich benennen: ohne Namen bricht jedes
                # spaetere ALTER TABLE dieses INSERT.
                "INSERT INTO rag_feedback ("
                " feedback_id, reported_by_user_id, reason, comment, question, answer,"
                " sources_json, passages_json, rights_json, runtime_json, request_id,"
                " severity, status, created_at, resolved_at, resolution_reason,"
                " document_ids_json, knowledgebase_ids_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, NULL, NULL, ?, ?)",
                (feedback_id, user_id, reason, comment.strip()[:2000], question[:8000], answer[:16000],
                 json.dumps(sources), json.dumps(passages), json.dumps(rights), json.dumps(runtime),
                 request_id[:200], severity, stamp, json.dumps(document_ids or []),
                 json.dumps(knowledgebase_ids or [])),
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

    def feedback_reporter(self, feedback_id: str) -> str:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT reported_by_user_id FROM rag_feedback WHERE feedback_id=?",
                (feedback_id,),
            ).fetchone()
        if not row:
            raise QualityCaseError("feedback_not_found")
        return row["reported_by_user_id"]

    def resolve(self, case_type: str, case_id: str, resolution_reason: str) -> None:
        reason = resolution_reason.strip()
        if len(reason) < 3:
            raise QualityCaseError("resolution_reason_required")
        table, id_column = {
            "feedback": ("rag_feedback", "feedback_id"),
            "incident": ("system_incidents", "incident_id"),
        }.get(case_type, (None, None))
        if not table:
            raise QualityCaseError("invalid_quality_case_type")
        with self.store.connect() as db:
            if table == "system_incidents":
                cursor = db.execute(
                    f"UPDATE {table} SET status='resolved', user_comment=?, updated_at=? "
                    f"WHERE {id_column}=? AND status='open'",
                    (reason[:2000], self.now(), case_id),
                )
            else:
                cursor = db.execute(
                    f"UPDATE {table} SET status='resolved', resolved_at=?, resolution_reason=? "
                    f"WHERE {id_column}=? AND status='open'",
                    (self.now(), reason[:2000], case_id),
                )
        if not cursor.rowcount:
            raise QualityCaseError("quality_case_not_found_or_resolved")


    def attach_screenshot(self, feedback_id: str, user_id: str, filename: str) -> None:
        """Vermerkt den geprueften Bildanhang an einer Meldung."""
        with self.store.connect() as db:
            row = db.execute(
                "SELECT reported_by_user_id FROM rag_feedback WHERE feedback_id = ?",
                (feedback_id,),
            ).fetchone()
            if not row:
                raise QualityCaseError("feedback_not_found")
            if row["reported_by_user_id"] != user_id:
                raise QualityCaseError("only_reporter_may_attach")
            db.execute(
                "UPDATE rag_feedback SET screenshot_filename = ? WHERE feedback_id = ?",
                (filename, feedback_id),
            )

    def add_attachment(
        self, feedback_id: str, user_id: str, *, attachment_id: str,
        original_filename: str, stored_filename: str, media_type: str, size_bytes: int,
    ) -> None:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT reported_by_user_id FROM rag_feedback WHERE feedback_id=?",
                (feedback_id,),
            ).fetchone()
            if not row:
                raise QualityCaseError("feedback_not_found")
            if row["reported_by_user_id"] != user_id:
                raise QualityCaseError("only_reporter_may_attach")
            count = db.execute(
                "SELECT COUNT(*) count FROM feedback_attachments WHERE feedback_id=?",
                (feedback_id,),
            ).fetchone()["count"]
            if count >= 5:
                raise QualityCaseError("feedback_attachment_limit_reached")
            db.execute(
                "INSERT INTO feedback_attachments VALUES (?,?,?,?,?,?,?)",
                (attachment_id, feedback_id, original_filename, stored_filename,
                 media_type, size_bytes, self.now()),
            )

    def attachments_of(self, feedback_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT attachment_id,original_filename,media_type,size_bytes,created_at "
                "FROM feedback_attachments WHERE feedback_id=? ORDER BY created_at,attachment_id",
                (feedback_id,),
            ).fetchall()]

    def attachment(self, feedback_id: str, attachment_id: str) -> dict[str, Any]:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM feedback_attachments WHERE feedback_id=? AND attachment_id=?",
                (feedback_id, attachment_id),
            ).fetchone()
        if not row:
            raise QualityCaseError("attachment_not_found")
        return dict(row)

    def screenshot_of(self, feedback_id: str) -> str | None:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT screenshot_filename FROM rag_feedback WHERE feedback_id = ?",
                (feedback_id,),
            ).fetchone()
        if not row:
            raise QualityCaseError("feedback_not_found")
        return row["screenshot_filename"]
