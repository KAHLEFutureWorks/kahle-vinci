from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import EligibleUser, InvalidUser


class SQLiteOpenWebUIUserReader:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._invalid_users: list[InvalidUser] = []

    def eligible_users(self) -> list[EligibleUser]:
        rows = self._read_rows()
        users: list[EligibleUser] = []
        invalid_users: list[InvalidUser] = []
        for row in rows:
            user, error_code = self._to_eligible_user(row)
            if user is None:
                user_id = str(row["id"] or "").strip()
                if user_id and error_code:
                    email = str(row["email"] or "").strip().lower()
                    invalid_users.append(InvalidUser(user_id, email, error_code))
            else:
                users.append(user)
        self._invalid_users = invalid_users
        return users

    def invalid_users(self) -> list[InvalidUser]:
        return list(self._invalid_users)

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
    def _to_eligible_user(row: sqlite3.Row) -> tuple[EligibleUser | None, str | None]:
        user_id = str(row["id"] or "").strip()
        email = str(row["email"] or "").strip().lower()
        raw_name = str(row["name"] or "").strip()
        name_parts = raw_name.split()
        if not user_id:
            return None, None
        if not SQLiteOpenWebUIUserReader._is_valid_email(email):
            return None, "invalid_email"
        if len(name_parts) >= 2:
            first_name = name_parts[0]
            last_name = " ".join(name_parts[1:])
        else:
            surname, separator, first_name = raw_name.partition(".")
            surname = surname.strip()
            first_name = first_name.strip()
            if not separator or not surname or not first_name or "." in first_name:
                return None, "invalid_name"
            last_name = surname
        return (
            EligibleUser(
                openwebui_id=user_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=str(row["role"] or "").strip().lower(),
            ),
            None,
        )

    @staticmethod
    def _is_valid_email(email: str) -> bool:
        local, separator, domain = email.partition("@")
        return bool(separator and local and domain and "." in domain)
