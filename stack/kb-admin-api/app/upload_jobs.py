from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Callable

try:
    from .portal_governance import SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import SQLiteGovernanceStore


class UploadJobError(ValueError):
    pass


class UploadJobService:
    """Persistent status records for asynchronous document processing."""

    STEPS = ("uploaded", "security", "conversion", "comparison", "completed")

    def __init__(
        self,
        store: SQLiteGovernanceStore,
        *,
        now: Callable[[], str] | None = None,
        identifier: Callable[[], str] | None = None,
    ):
        self.store = store
        self.now = now or (lambda: datetime.now().astimezone().isoformat())
        self.identifier = identifier or (lambda: str(uuid.uuid4()))
        with self.store.connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS upload_jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    step TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    result_json TEXT,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )

    def create(self, user_id: str) -> str:
        job_id, stamp = self.identifier(), self.now()
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO upload_jobs VALUES (?,?, 'queued','uploaded',5,NULL,NULL,?,?)",
                (job_id, user_id, stamp, stamp),
            )
        return job_id

    def progress(self, job_id: str, step: str, progress: int) -> None:
        if step not in self.STEPS or not 0 <= progress <= 100:
            raise UploadJobError("invalid_upload_progress")
        with self.store.connect() as db:
            db.execute(
                "UPDATE upload_jobs SET status='processing', step=?, progress=?, updated_at=? WHERE job_id=?",
                (step, progress, self.now(), job_id),
            )

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        with self.store.connect() as db:
            db.execute(
                "UPDATE upload_jobs SET status='completed', step='completed', progress=100, "
                "result_json=?, updated_at=? WHERE job_id=?",
                (json.dumps(result, ensure_ascii=False), self.now(), job_id),
            )

    def fail(self, job_id: str, error_code: str) -> None:
        with self.store.connect() as db:
            db.execute(
                "UPDATE upload_jobs SET status='failed', error_code=?, updated_at=? WHERE job_id=?",
                (error_code[:300], self.now(), job_id),
            )

    def get(self, job_id: str, user_id: str, is_admin: bool = False) -> dict[str, Any]:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM upload_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or (row["user_id"] != user_id and not is_admin):
            raise UploadJobError("upload_job_not_found")
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json")) if result.get("result_json") else None
        return result
