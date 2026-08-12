from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from .maintenance import workdays_until
    from .portal_governance import SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from maintenance import workdays_until
    from portal_governance import SQLiteGovernanceStore


class QualityDashboard:
    def __init__(self, store: SQLiteGovernanceStore, backup_state_path: Path):
        self.store, self.backup_state_path = store, backup_state_path
        with self.store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS retrieval_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL DEFAULT (datetime('now')),
                user_id TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                found INTEGER NOT NULL CHECK(found IN (0,1)),
                source_count INTEGER NOT NULL CHECK(source_count >= 0),
                latency_ms INTEGER NOT NULL CHECK(latency_ms >= 0),
                error_code TEXT
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_retrieval_events_occurred ON retrieval_events(occurred_at)")

    def record_retrieval(self, *, user_id: str, query_hash: str, found: bool,
                         source_count: int, latency_ms: int,
                         error_code: str | None = None) -> None:
        if not user_id.strip() or len(query_hash) != 64:
            raise ValueError("valid_retrieval_identity_and_hash_required")
        with self.store.connect() as db:
            db.execute(
                """INSERT INTO retrieval_events
                   (user_id,query_hash,found,source_count,latency_ms,error_code)
                   VALUES(?,?,?,?,?,?)""",
                (user_id.strip(), query_hash.lower(), int(found), max(0, source_count),
                 max(0, latency_ms), (error_code or "")[:100] or None),
            )

    def snapshot(self, today: date | None = None) -> dict[str, Any]:
        today = today or date.today()
        with self.store.connect() as db:
            active = db.execute("SELECT COUNT(*) count FROM document_versions WHERE status='active'").fetchone()["count"]
            expiry_dates = [row["valid_until"] for row in db.execute(
                "SELECT valid_until FROM document_versions WHERE status='active' AND valid_until IS NOT NULL"
            ).fetchall()]
            cases = {row["status"]: row["count"] for row in db.execute(
                "SELECT status, COUNT(*) count FROM document_cases GROUP BY status"
            ).fetchall()}
            case_rows = db.execute(
                "SELECT status,requires_admin,analysis_json,created_at,updated_at FROM document_cases"
            ).fetchall()
            expired_documents = db.execute(
                "SELECT COUNT(*) count FROM document_versions WHERE status='expired'"
            ).fetchone()["count"]
            incidents = db.execute("SELECT COUNT(*) count FROM system_incidents WHERE status='open'").fetchone()["count"]
            feedback = db.execute("SELECT COUNT(*) count FROM rag_feedback WHERE status='open'").fetchone()["count"]
            migration = {row["status"]: row["count"] for row in db.execute(
                "SELECT status, COUNT(*) count FROM migration_inventory GROUP BY status"
            ).fetchall()}
            outbox = db.execute(
                "SELECT COUNT(*) pending, SUM(CASE WHEN attempts > 0 THEN 1 ELSE 0 END) failed FROM notification_outbox WHERE status='pending'"
            ).fetchone()
            managers_without_delegate = db.execute(
                """SELECT COUNT(*) count FROM portal_users u
                   WHERE u.active=1 AND u.role='manager' AND NOT EXISTS (
                     SELECT 1 FROM manager_delegates d WHERE d.manager_user_id=u.user_id
                     AND (d.valid_until IS NULL OR d.valid_until>=?)
                   )""", (today.isoformat(),)
            ).fetchone()["count"]
            documents_without_responsibility = db.execute(
                """SELECT COUNT(*) count FROM canonical_documents d
                   LEFT JOIN portal_users o ON o.user_id=d.owner_user_id AND o.active=1
                   LEFT JOIN portal_users m ON m.user_id=o.manager_user_id AND m.active=1
                   WHERE d.active_version_id IS NOT NULL AND (o.user_id IS NULL OR m.user_id IS NULL)"""
            ).fetchone()["count"]
            retrieval_rows = db.execute(
                """SELECT found,source_count,latency_ms,error_code FROM retrieval_events
                   WHERE occurred_at >= datetime('now','-30 days') ORDER BY latency_ms"""
            ).fetchall()
        backup = {}
        try:
            backup = json.loads(self.backup_state_path.read_text(encoding="utf-8"))
        except Exception:
            backup = {"status": "not_configured_or_not_run"}
        retrieval_total = len(retrieval_rows)
        retrieval_found = sum(row["found"] for row in retrieval_rows)
        answered_with_sources = sum(bool(row["found"] and row["source_count"] > 0) for row in retrieval_rows)
        errors = sum(bool(row["error_code"]) for row in retrieval_rows)
        latencies = [row["latency_ms"] for row in retrieval_rows]
        p95_index = max(0, math.ceil(len(latencies) * .95) - 1)
        approval_statuses = {"pending_manager_approval", "pending_admin_approval", "ready_to_activate"}
        terminal_statuses = {"active", "rejected", "withdrawn"}
        terminal_minutes = [
            (datetime.fromisoformat(row["updated_at"]) - datetime.fromisoformat(row["created_at"])).total_seconds() / 60
            for row in case_rows if row["status"] in terminal_statuses
        ]
        analyses = [json.loads(row["analysis_json"] or "{}") for row in case_rows]
        open_approvals = sum(row["status"] in approval_statuses for row in case_rows)
        overdue = sum(
            row["status"] in approval_statuses
            and workdays_until(date.fromisoformat(row["created_at"][:10]), today) >= 6
            for row in case_rows
        )
        return {
            "active_documents": active,
            "expired_documents": expired_documents,
            "expiring_within_15_workdays": sum(0 <= workdays_until(today, date.fromisoformat(value)) <= 15 for value in expiry_dates),
            "workflow_cases": cases, "open_incidents": incidents, "open_feedback": feedback,
            "workflow_quality": {
                "open_approvals": open_approvals,
                "average_processing_minutes": round(sum(terminal_minutes) / len(terminal_minutes), 1) if terminal_minutes else None,
                "escalations": sum(bool(row["requires_admin"]) and row["status"] not in terminal_statuses for row in case_rows),
                "overdue_cases": overdue,
                "duplicates": sum(bool(item.get("exact_duplicate_document_id") or item.get("normalized_duplicate_document_id")) for item in analyses),
                "version_candidates": sum(bool(item.get("version_candidate_document_ids")) for item in analyses),
                "conflicts": sum(bool(item.get("contradiction_document_ids")) for item in analyses),
                "failed_conversions": sum(item.get("conversion_quality") == "failed" for item in analyses),
                "security_findings": sum(item.get("prompt_injection_risk") in {"medium", "high", "critical"} or item.get("malware_safe") is False for item in analyses),
            },
            "migration": migration, "mail": {"pending": outbox["pending"], "failed": outbox["failed"] or 0},
            "governance": {
                "managers_without_delegate": managers_without_delegate,
                "documents_without_active_owner_or_manager": documents_without_responsibility,
            },
            "retrieval": {
                "window_days": 30,
                "requests": retrieval_total,
                "document_hit_rate_percent": round(100 * retrieval_found / retrieval_total, 1) if retrieval_total else None,
                "source_coverage_percent": round(100 * answered_with_sources / retrieval_found, 1) if retrieval_found else None,
                "unanswered_questions": sum(not row["found"] and not row["error_code"] for row in retrieval_rows),
                "average_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
                "p95_latency_ms": latencies[p95_index] if latencies else None,
                "error_rate_percent": round(100 * errors / retrieval_total, 1) if retrieval_total else None,
            },
            "backup": backup,
        }
