from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

try:
    from .portal_governance import SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import SQLiteGovernanceStore


class DecisionJobError(ValueError):
    pass


class DecisionJobQueue:
    """Persistent single-consumer queue for activation and index-changing decisions."""

    def __init__(self, store: SQLiteGovernanceStore, *, identifier: Callable[[], str] | None = None,
                 now: Callable[[], datetime] | None = None, lease_minutes: int = 15):
        self.store = store
        self.identifier = identifier or (lambda: str(uuid.uuid4()))
        self.now = now or (lambda: datetime.now().astimezone())
        self.lease_minutes = lease_minutes
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS decision_jobs (
                job_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, user_id TEXT NOT NULL,
                decision TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL,
                result_json TEXT, error_code TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, lease_expires_at TEXT
            )""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_active_decision_case
                          ON decision_jobs(case_id) WHERE status IN ('queued','processing')""")

    def enqueue(self, case_id: str, user_id: str, decision: str, reason: str) -> dict[str, Any]:
        stamp = self.now().isoformat()
        with self.store.connect() as db:
            existing = db.execute(
                "SELECT job_id FROM decision_jobs WHERE case_id=? AND status IN ('queued','processing')",
                (case_id,),
            ).fetchone()
            if existing:
                return self.get(existing["job_id"], user_id, is_admin=True)
            job_id = self.identifier()
            db.execute(
                "INSERT INTO decision_jobs VALUES (?,?,?,?,?,'queued',NULL,NULL,?,?,NULL)",
                (job_id, case_id, user_id, decision, reason, stamp, stamp),
            )
        return self.get(job_id, user_id, is_admin=True)

    def claim_next(self) -> dict[str, Any] | None:
        now = self.now(); stamp = now.isoformat()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE decision_jobs SET status='queued',lease_expires_at=NULL,updated_at=? "
                "WHERE status='processing' AND lease_expires_at<?", (stamp, stamp),
            )
            if db.execute("SELECT 1 FROM decision_jobs WHERE status='processing' LIMIT 1").fetchone():
                return None
            row = db.execute(
                "SELECT * FROM decision_jobs WHERE status='queued' ORDER BY created_at,job_id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            lease = (now + timedelta(minutes=self.lease_minutes)).isoformat()
            db.execute(
                "UPDATE decision_jobs SET status='processing',updated_at=?,lease_expires_at=? WHERE job_id=?",
                (stamp, lease, row["job_id"]),
            )
        return self.get(row["job_id"], row["user_id"], is_admin=True)

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        with self.store.connect() as db:
            db.execute(
                "UPDATE decision_jobs SET status='completed',result_json=?,lease_expires_at=NULL,updated_at=? WHERE job_id=?",
                (json.dumps(result, ensure_ascii=False), self.now().isoformat(), job_id),
            )

    def fail(self, job_id: str, error_code: str) -> None:
        with self.store.connect() as db:
            db.execute(
                "UPDATE decision_jobs SET status='failed',error_code=?,lease_expires_at=NULL,updated_at=? WHERE job_id=?",
                (error_code[:500], self.now().isoformat(), job_id),
            )

    def get(self, job_id: str, user_id: str, is_admin: bool = False) -> dict[str, Any]:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM decision_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row or (row["user_id"] != user_id and not is_admin):
                raise DecisionJobError("decision_job_not_found")
            result = dict(row)
            if result["status"] == "queued":
                result["position"] = db.execute(
                    "SELECT COUNT(*) FROM decision_jobs WHERE status='queued' AND (created_at<? OR (created_at=? AND job_id<=?))",
                    (row["created_at"], row["created_at"], row["job_id"]),
                ).fetchone()[0]
            else:
                result["position"] = 0
        result["result"] = json.loads(result.pop("result_json")) if result.get("result_json") else None
        return result

    def list_active(self, user_id: str, is_admin: bool = False) -> list[dict[str, Any]]:
        """Return durable queued work so the UI need not keep a polling request open."""
        with self.store.connect() as db:
            if is_admin:
                rows = db.execute(
                    "SELECT job_id,user_id FROM decision_jobs WHERE status IN ('queued','processing') "
                    "ORDER BY created_at,job_id"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT job_id,user_id FROM decision_jobs WHERE user_id=? AND status IN ('queued','processing') "
                    "ORDER BY created_at,job_id", (user_id,),
                ).fetchall()
        return [self.get(row["job_id"], row["user_id"], is_admin=True) for row in rows]
