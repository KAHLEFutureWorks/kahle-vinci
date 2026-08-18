from __future__ import annotations

import sqlite3
from pathlib import Path


class SQLiteProvisioningStateStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def was_completed(self, openwebui_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT completed_at FROM provisioning_state WHERE openwebui_id = ?",
                (openwebui_id,),
            ).fetchone()
        return bool(row and row["completed_at"] is not None)

    def member_id(self, openwebui_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT member_id FROM provisioning_state WHERE openwebui_id = ?",
                (openwebui_id,),
            ).fetchone()
        return str(row["member_id"]) if row and row["member_id"] else None

    def last_error(self, openwebui_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT last_error FROM provisioning_state WHERE openwebui_id = ?",
                (openwebui_id,),
            ).fetchone()
        return str(row["last_error"]) if row and row["last_error"] else None

    def record_completed(self, openwebui_id: str, member_id: str, *, now_epoch: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO provisioning_state(openwebui_id, member_id, completed_at, last_error, updated_at)
                VALUES (?, ?, ?, NULL, ?)
                ON CONFLICT(openwebui_id) DO UPDATE SET
                    member_id=excluded.member_id,
                    completed_at=excluded.completed_at,
                    last_error=NULL,
                    updated_at=excluded.updated_at
                """,
                (openwebui_id, member_id, now_epoch, now_epoch),
            )

    def record_failure(self, openwebui_id: str, error_code: str, *, now_epoch: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO provisioning_state(openwebui_id, member_id, completed_at, last_error, updated_at)
                VALUES (?, NULL, NULL, ?, ?)
                ON CONFLICT(openwebui_id) DO UPDATE SET
                    last_error=excluded.last_error,
                    updated_at=excluded.updated_at
                """,
                (openwebui_id, error_code, now_epoch),
            )

    def record_heartbeat(self, epoch_seconds: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO worker_state(key, value) VALUES ('heartbeat_epoch', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(epoch_seconds),),
            )

    def welcome_was_sent(self, email: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT sent_at FROM welcome_mail_state WHERE email = ?",
                (email.strip().lower(),),
            ).fetchone()
        return bool(row and row["sent_at"] is not None)

    def record_welcome_sent(self, email: str, *, now_epoch: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO welcome_mail_state(email, sent_at) VALUES (?, ?)
                ON CONFLICT(email) DO UPDATE SET sent_at=excluded.sent_at
                """,
                (email.strip().lower(), now_epoch),
            )

    def pending_notice_was_sent(self, pending_user_id: str, admin_email: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT sent_at FROM pending_admin_notification
                WHERE pending_user_id = ? AND admin_email = ?
                """,
                (pending_user_id, admin_email.strip().lower()),
            ).fetchone()
        return bool(row and row["sent_at"] is not None)

    def record_pending_notice_sent(
        self, pending_user_id: str, admin_email: str, *, now_epoch: int
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pending_admin_notification(pending_user_id, admin_email, sent_at)
                VALUES (?, ?, ?)
                ON CONFLICT(pending_user_id, admin_email) DO UPDATE SET sent_at=excluded.sent_at
                """,
                (pending_user_id, admin_email.strip().lower(), now_epoch),
            )

    def heartbeat_epoch(self) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM worker_state WHERE key = 'heartbeat_epoch'"
            ).fetchone()
        return int(row["value"]) if row else None

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS provisioning_state (
                    openwebui_id TEXT PRIMARY KEY,
                    member_id TEXT,
                    completed_at INTEGER,
                    last_error TEXT,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS welcome_mail_state (
                    email TEXT PRIMARY KEY,
                    sent_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_admin_notification (
                    pending_user_id TEXT NOT NULL,
                    admin_email TEXT NOT NULL,
                    sent_at INTEGER NOT NULL,
                    PRIMARY KEY(pending_user_id, admin_email)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=20)
        connection.row_factory = sqlite3.Row
        return connection
