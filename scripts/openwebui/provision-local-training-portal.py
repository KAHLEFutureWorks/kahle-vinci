"""Configure the two local training identities in the Wissensportal database."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone


DB_PATH = "/portal-data/wissensportal.sqlite3"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    if len(sys.argv) != 7:
        raise SystemExit(
            "usage: provision-local-training-portal.py "
            "<employee-id> <employee-email> <employee-name> "
            "<manager-id> <manager-email> <manager-name>"
        )
    employee_id, employee_email, employee_name = sys.argv[1:4]
    manager_id, manager_email, manager_name = sys.argv[4:7]
    stamp = now()

    with sqlite3.connect(DB_PATH) as db:
        db.execute("PRAGMA foreign_keys = ON")
        for user_id, email, name, role, manager_user_id in (
            (manager_id, manager_email, manager_name, "manager", None),
            (employee_id, employee_email, employee_name, "employee", manager_id),
        ):
            db.execute(
                """
                INSERT INTO portal_users (
                    user_id, email, display_name, active, role,
                    manager_user_id, created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    email=excluded.email,
                    display_name=excluded.display_name,
                    active=1,
                    role=excluded.role,
                    manager_user_id=excluded.manager_user_id,
                    updated_at=excluded.updated_at
                """,
                (user_id, email, name, role, manager_user_id, stamp, stamp),
            )

        # Training accounts may demonstrate search and upload in every active area.
        knowledgebases = db.execute(
            "SELECT knowledgebase_id FROM knowledgebases WHERE status = 'active'"
        ).fetchall()
        for (knowledgebase_id,) in knowledgebases:
            for user_id in (employee_id, manager_id):
                db.execute(
                    """
                    INSERT INTO knowledgebase_access (
                        user_id, knowledgebase_id, can_read, can_upload, updated_at
                    ) VALUES (?, ?, 1, 1, ?)
                    ON CONFLICT(user_id, knowledgebase_id) DO UPDATE SET
                        can_read=1, can_upload=1, updated_at=excluded.updated_at
                    """,
                    (user_id, knowledgebase_id, stamp),
                )

    print(json.dumps({"employee_id": employee_id, "manager_id": manager_id}))


if __name__ == "__main__":
    main()
