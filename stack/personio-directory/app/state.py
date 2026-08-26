from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone


class SQLiteSyncState:
    """Durable sync progress with success state committed as one transaction."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sync_state(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS indexed_person(
                    personio_id TEXT PRIMARY KEY,
                    source_updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sync_run(
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    started_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    status TEXT NOT NULL,
                    error_code TEXT
                );
                """
            )

    @contextmanager
    def run(self, kind: str) -> Iterator["SyncRun"]:
        if kind not in {"delta", "full"}:
            raise ValueError("sync_kind_invalid")
        connection = self._connect()
        cursor = connection.execute(
            "INSERT INTO sync_run(kind, started_at, status) VALUES (?, ?, 'running')",
            (kind, int(time.time())),
        )
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        run = SyncRun(connection, int(cursor.lastrowid), kind)
        try:
            yield run
            if not run._success_at:
                raise RuntimeError("sync_success_not_marked")
            run._commit_success()
            connection.commit()
        except Exception:
            connection.rollback()
            connection.execute(
                "UPDATE sync_run SET completed_at = ?, status = 'failed', error_code = ? WHERE id = ?",
                (int(time.time()), "sync_failed", run.id),
            )
            connection.commit()
            raise
        finally:
            connection.close()

    def _value(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def last_successful_delta_at(self) -> str | None:
        return self._value("last_successful_delta_at")

    def last_successful_full_at(self) -> str | None:
        return self._value("last_successful_full_at")

    def last_successful_at(self) -> str | None:
        """Return the newest committed sync timestamp, without trusting a running run."""
        values = (
            value
            for value in (self.last_successful_delta_at(), self.last_successful_full_at())
            if value
        )
        try:
            return max(values, key=_parse_timestamp)
        except ValueError:
            return None

    def indexed_people(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT personio_id, source_updated_at FROM indexed_person ORDER BY personio_id"
            ).fetchall()
        return {str(row["personio_id"]): str(row["source_updated_at"]) for row in rows}

    def last_run_status(self) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT status FROM sync_run ORDER BY id DESC LIMIT 1").fetchone()
        return str(row["status"]) if row else None


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class SyncRun:
    def __init__(self, connection: sqlite3.Connection, run_id: int, kind: str) -> None:
        self._connection = connection
        self.id = run_id
        self.kind = kind
        self._snapshot: dict[str, str] | None = None
        self._success_at: str | None = None

    def replace_indexed_people(self, people: dict[str, str]) -> None:
        self._snapshot = dict(people)

    def mark_success(self, completed_at: str) -> None:
        self._success_at = completed_at

    def _commit_success(self) -> None:
        assert self._success_at is not None
        if self._snapshot is not None:
            self._connection.execute("DELETE FROM indexed_person")
            self._connection.executemany(
                "INSERT INTO indexed_person(personio_id, source_updated_at) VALUES (?, ?)",
                sorted(self._snapshot.items()),
            )
        self._connection.execute(
            "INSERT INTO sync_state(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"last_successful_{self.kind}_at", self._success_at),
        )
        self._connection.execute(
            "UPDATE sync_run SET completed_at = ?, status = 'completed', error_code = NULL WHERE id = ?",
            (int(time.time()), self.id),
        )
