from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

try:
    from .portal_governance import SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import SQLiteGovernanceStore


class UploadJobError(ValueError):
    pass


class UploadSpool:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, job_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job_id or ""):
            raise UploadJobError("invalid_upload_job_id")
        return self.root / f"{job_id}.upload"

    def stage(self, job_id: str, data: bytes) -> Path:
        target = self._path(job_id)
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".upload-job-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return target

    def read(self, job_id: str) -> bytes:
        return self._path(job_id).read_bytes()

    def remove(self, job_id: str) -> None:
        self._path(job_id).unlink(missing_ok=True)


class UploadJobService:
    """Persistent status records for asynchronous document processing."""

    STEPS = ("uploaded", "security", "conversion", "comparison", "completed")

    def __init__(
        self,
        store: SQLiteGovernanceStore,
        *,
        now: Callable[[], str | datetime] | None = None,
        identifier: Callable[[], str] | None = None,
        lease_minutes: int = 15,
    ):
        self.store = store
        self.now = now or (lambda: datetime.now().astimezone().isoformat())
        self.identifier = identifier or (lambda: str(uuid.uuid4()))
        self.lease_minutes = max(1, lease_minutes)
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
            columns = {row["name"] for row in db.execute("PRAGMA table_info(upload_jobs)")}
            additions = {
                "original_filename": "TEXT", "title": "TEXT",
                "knowledgebase_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "valid_workdays": "INTEGER", "confidentiality": "TEXT", "owner_user_id": "TEXT",
                "security_review_requested": "INTEGER NOT NULL DEFAULT 0", "staged_path": "TEXT",
                "file_size_bytes": "INTEGER NOT NULL DEFAULT 0", "lease_expires_at": "TEXT",
                "incident_id": "TEXT",
            }
            for name, definition in additions.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE upload_jobs ADD COLUMN {name} {definition}")

    def _now_datetime(self) -> datetime:
        value = self.now()
        return value if isinstance(value, datetime) else datetime.fromisoformat(value)

    def _stamp(self) -> str:
        return self._now_datetime().isoformat()

    def create(self, user_id: str) -> str:
        job_id, stamp = self.identifier(), self._stamp()
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO upload_jobs (job_id,user_id,status,step,progress,result_json,error_code,created_at,updated_at) "
                "VALUES (?,?,'queued','uploaded',5,NULL,NULL,?,?)",
                (job_id, user_id, stamp, stamp),
            )
        return job_id

    def enqueue(self, *, job_id: str, user_id: str, original_filename: str, title: str,
                knowledgebase_ids: tuple[str, ...], valid_workdays: int, confidentiality: str,
                owner_user_id: str, security_review_requested: bool, staged_path: str,
                file_size_bytes: int) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job_id or ""):
            raise UploadJobError("invalid_upload_job_id")
        stamp = self._stamp()
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO upload_jobs (job_id,user_id,status,step,progress,result_json,error_code,created_at,updated_at,"
                "original_filename,title,knowledgebase_ids_json,valid_workdays,confidentiality,owner_user_id,"
                "security_review_requested,staged_path,file_size_bytes,lease_expires_at,incident_id) "
                "VALUES (?,?,'queued','uploaded',5,NULL,NULL,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)",
                (job_id, user_id, stamp, stamp, original_filename, title,
                 json.dumps(list(knowledgebase_ids), ensure_ascii=False), valid_workdays, confidentiality,
                 owner_user_id, int(security_review_requested), staged_path, max(0, file_size_bytes)),
            )
        return self.get(job_id, user_id, is_admin=True)

    def progress(self, job_id: str, step: str, progress: int) -> None:
        if step not in self.STEPS or not 0 <= progress <= 100:
            raise UploadJobError("invalid_upload_progress")
        with self.store.connect() as db:
            db.execute(
                "UPDATE upload_jobs SET status='processing', step=?, progress=?, updated_at=? WHERE job_id=?",
                (step, progress, self._stamp(), job_id),
            )

    def heartbeat(self, job_id: str, step: str, progress: int) -> None:
        if step not in self.STEPS or not 0 <= progress <= 100:
            raise UploadJobError("invalid_upload_progress")
        now = self._now_datetime()
        with self.store.connect() as db:
            db.execute(
                "UPDATE upload_jobs SET status='processing',step=?,progress=?,updated_at=?,lease_expires_at=? "
                "WHERE job_id=? AND status='processing'",
                (step, progress, now.isoformat(), (now + timedelta(minutes=self.lease_minutes)).isoformat(), job_id),
            )

    def claim_next(self) -> dict[str, Any] | None:
        claimed, _ = self.recover_and_claim_next()
        return claimed

    def recover_and_claim_next(self) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        now = self._now_datetime(); stamp = now.isoformat()
        recovered_rows: list[tuple[str, str]] = []
        claimed_row: tuple[str, str] | None = None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            stale = db.execute(
                "SELECT job_id,user_id FROM upload_jobs WHERE status='processing' AND "
                "(lease_expires_at IS NULL OR lease_expires_at<?) ORDER BY created_at,job_id",
                (stamp,),
            ).fetchall()
            recovered_rows = [(row["job_id"], row["user_id"]) for row in stale]
            if recovered_rows:
                db.execute(
                    "UPDATE upload_jobs SET status='failed',error_code='upload_worker_interrupted',"
                    "lease_expires_at=NULL,updated_at=? WHERE status='processing' AND "
                    "(lease_expires_at IS NULL OR lease_expires_at<?)",
                    (stamp, stamp),
                )
            if db.execute("SELECT 1 FROM upload_jobs WHERE status='processing' LIMIT 1").fetchone():
                row = None
            else:
                row = db.execute(
                    "SELECT job_id,user_id FROM upload_jobs WHERE status='queued' ORDER BY created_at,job_id LIMIT 1"
                ).fetchone()
            if row:
                claimed_row = (row["job_id"], row["user_id"])
                db.execute(
                    "UPDATE upload_jobs SET status='processing',updated_at=?,lease_expires_at=? WHERE job_id=?",
                    (stamp, (now + timedelta(minutes=self.lease_minutes)).isoformat(), row["job_id"]),
                )
        recovered = [self.get(job_id, user_id, is_admin=True) for job_id, user_id in recovered_rows]
        claimed = self.get(*claimed_row, is_admin=True) if claimed_row else None
        return claimed, recovered

    def expire_interrupted(self) -> list[dict[str, Any]]:
        stamp = self._stamp()
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT job_id,user_id FROM upload_jobs WHERE status='processing' AND "
                "(lease_expires_at IS NULL OR lease_expires_at<?)",
                (stamp,),
            ).fetchall()
            expired = [self.get(row["job_id"], row["user_id"], is_admin=True) for row in rows]
            db.execute(
                "UPDATE upload_jobs SET status='failed',error_code='upload_worker_interrupted',"
                "lease_expires_at=NULL,updated_at=? WHERE status='processing' AND "
                "(lease_expires_at IS NULL OR lease_expires_at<?)",
                (stamp, stamp),
            )
        return expired

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        with self.store.connect() as db:
            db.execute(
                "UPDATE upload_jobs SET status='completed', step='completed', progress=100, "
                "result_json=?, lease_expires_at=NULL, updated_at=? WHERE job_id=?",
                (json.dumps(result, ensure_ascii=False), self._stamp(), job_id),
            )

    def fail(self, job_id: str, error_code: str) -> None:
        with self.store.connect() as db:
            db.execute(
                "UPDATE upload_jobs SET status='failed', error_code=?, lease_expires_at=NULL, updated_at=? WHERE job_id=?",
                (error_code[:300], self._stamp(), job_id),
            )

    def set_incident(self, job_id: str, incident_id: str) -> None:
        with self.store.connect() as db:
            db.execute("UPDATE upload_jobs SET incident_id=?,updated_at=? WHERE job_id=?",
                       (incident_id, self._stamp(), job_id))

    def get(self, job_id: str, user_id: str, is_admin: bool = False) -> dict[str, Any]:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM upload_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or (row["user_id"] != user_id and not is_admin):
            raise UploadJobError("upload_job_not_found")
        result = dict(row)
        result["knowledgebase_ids"] = json.loads(result.pop("knowledgebase_ids_json") or "[]")
        result["security_review_requested"] = bool(result.get("security_review_requested"))
        if result["status"] == "queued":
            with self.store.connect() as db:
                result["position"] = db.execute(
                    "SELECT COUNT(*) FROM upload_jobs WHERE status='queued' AND "
                    "(created_at<? OR (created_at=? AND job_id<=?))",
                    (result["created_at"], result["created_at"], result["job_id"]),
                ).fetchone()[0]
        else:
            result["position"] = 0
        result["result"] = json.loads(result.pop("result_json")) if result.get("result_json") else None
        return result

    def list_active(self, user_id: str, is_admin: bool = False) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            if is_admin:
                rows = db.execute(
                    "SELECT job_id,user_id FROM upload_jobs WHERE status IN ('queued','processing') "
                    "ORDER BY created_at,job_id"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT job_id,user_id FROM upload_jobs WHERE user_id=? AND status IN ('queued','processing') "
                    "ORDER BY created_at,job_id", (user_id,),
                ).fetchall()
        return [self.get(row["job_id"], row["user_id"], is_admin=True) for row in rows]
