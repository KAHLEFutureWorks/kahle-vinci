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
            "backup": backup,
        }
