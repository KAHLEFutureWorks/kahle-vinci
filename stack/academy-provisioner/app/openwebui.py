from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import EligibleUser


class SQLiteOpenWebUIUserReader:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._invalid_user_ids: list[str] = []

    def eligible_users(self) -> list[EligibleUser]:
        rows = self._read_rows()
        users: list[EligibleUser] = []
        invalid_user_ids: list[str] = []
        for row in rows:
            user = self._to_eligible_user(row)
            if user is None:
                invalid_user_ids.append(str(row["id"] or ""))
            else:
                users.append(user)
        self._invalid_user_ids = [user_id for user_id in invalid_user_ids if user_id]
        return users

    def invalid_user_ids(self) -> list[str]:
        return list(self._invalid_user_ids)

    def _read_rows(self) -> list[sqlite3.Row]:
        database_uri = f"file:{self.database_path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(database_uri, uri=True, timeout=20)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(
                """
                SELECT id, name, email, role
                FROM user
                WHERE lower(coalesce(role, '')) IN ('user', 'admin')
                ORDER BY id
                """
            ).fetchall()
        finally:
            connection.close()

    @staticmethod
    def _to_eligible_user(row: sqlite3.Row) -> EligibleUser | None:
        user_id = str(row["id"] or "").strip()
        email = str(row["email"] or "").strip().lower()
        name_parts = str(row["name"] or "").split()
        if not user_id or not SQLiteOpenWebUIUserReader._is_valid_email(email):
            return None
        if len(name_parts) < 2:
            return None
        return EligibleUser(
            openwebui_id=user_id,
            email=email,
            first_name=name_parts[0],
            last_name=" ".join(name_parts[1:]),
            role=str(row["role"] or "").strip().lower(),
        )

    @staticmethod
    def _is_valid_email(email: str) -> bool:
        local, separator, domain = email.partition("@")
        return bool(separator and local and domain and "." in domain)
