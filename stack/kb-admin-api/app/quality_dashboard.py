from __future__ import annotations

import json
from datetime import date
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
        backup = {}
        try:
            backup = json.loads(self.backup_state_path.read_text(encoding="utf-8"))
        except Exception:
            backup = {"status": "not_configured_or_not_run"}
        return {
            "active_documents": active,
            "expiring_within_15_workdays": sum(0 <= workdays_until(today, date.fromisoformat(value)) <= 15 for value in expiry_dates),
            "workflow_cases": cases, "open_incidents": incidents, "open_feedback": feedback,
            "migration": migration, "mail": {"pending": outbox["pending"], "failed": outbox["failed"] or 0},
            "governance": {
                "managers_without_delegate": managers_without_delegate,
                "documents_without_active_owner_or_manager": documents_without_responsibility,
            },
            "backup": backup,
        }
