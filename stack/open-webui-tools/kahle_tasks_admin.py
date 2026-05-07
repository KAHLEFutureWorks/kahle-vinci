"""
title: KAHLE Tasks Admin
author: local
version: 0.1.0
description: Admin-Diagnose fuer die zentrale KAHLE-Vinci Aufgaben-Datenbank.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any


DB_PATH = Path(os.getenv("KAHLE_TASKS_DB_PATH", "/app/backend/data/kahle_vinci_tasks.db"))
OWUI_DB_PATH = Path(os.getenv("OWUI_DB_PATH", "/app/backend/data/webui.db"))


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _require_admin(__user__: dict | None) -> None:
    role = ""
    if isinstance(__user__, dict):
        role = str(__user__.get("role") or "").strip().lower()
    if role != "admin":
        raise PermissionError("Nur OpenWebUI-Admins duerfen die Aufgaben-Admin-Diagnose nutzen.")


def _connect_existing() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _connect_webui() -> sqlite3.Connection | None:
    if not OWUI_DB_PATH.exists():
        return None
    con = sqlite3.connect(OWUI_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection) -> bool:
    row = con.execute("select 1 from sqlite_master where type='table' and name='tasks'").fetchone()
    return bool(row)


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in ("created_at", "updated_at", "completed_at"):
        if data.get(key) is not None:
            data[key] = int(data[key])
    return data


def _load_users(user_ids: list[str]) -> dict[str, dict[str, str]]:
    users = {user_id: {"id": user_id, "name": "", "email": "", "role": ""} for user_id in user_ids}
    if not user_ids:
        return users
    webui = _connect_webui()
    if not webui:
        return users
    try:
        placeholders = ",".join("?" for _ in user_ids)
        rows = webui.execute(
            f"select id, name, email, role from user where id in ({placeholders})",
            user_ids,
        ).fetchall()
        for row in rows:
            users[row["id"]] = {
                "id": row["id"],
                "name": row["name"] or "",
                "email": row["email"] or "",
                "role": row["role"] or "",
            }
    finally:
        webui.close()
    return users


def _user_label(user: dict[str, str]) -> str:
    if user.get("name") and user.get("email"):
        return f"{user['name']} <{user['email']}>"
    return user.get("name") or user.get("email") or user.get("id", "")


def _build_user_breakdown(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        select user_id, status, count(*) as count
        from tasks
        group by user_id, status
        order by user_id, status
        """
    ).fetchall()
    users = _load_users(sorted({row["user_id"] for row in rows}))
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        grouped.setdefault(row["user_id"], {"by_status": {}, "count": 0})
        grouped[row["user_id"]]["by_status"][row["status"]] = int(row["count"])
        grouped[row["user_id"]]["count"] += int(row["count"])

    result = []
    for index, user_id in enumerate(sorted(grouped), start=1):
        user = users.get(user_id, {"id": user_id, "name": "", "email": "", "role": ""})
        result.append(
            {
                "user_index": index,
                "user_id": user_id,
                "user_name": user.get("name", ""),
                "user_email": user.get("email", ""),
                "user_label": _user_label(user),
                "count": int(grouped[user_id]["count"]),
                "by_status": grouped[user_id]["by_status"],
            }
        )
    return result


def _resolve_user(con: sqlite3.Connection, user: str, user_index: int = 0) -> dict[str, str]:
    task_user_ids = [row["user_id"] for row in con.execute("select distinct user_id from tasks order by user_id").fetchall()]
    users = _load_users(task_user_ids)
    user = str(user or "").strip()

    if user_index:
        if user_index < 1 or user_index > len(task_user_ids):
            raise ValueError(f"user_index ausserhalb des Bereichs: {user_index}")
        user_id = task_user_ids[user_index - 1]
        return users.get(user_id, {"id": user_id, "name": "", "email": "", "role": ""})

    lowered = user.lower()
    if lowered.startswith("nutzer "):
        try:
            return _resolve_user(con, "", int(lowered.split(" ", 1)[1].strip()))
        except ValueError:
            pass

    if user in users:
        return users[user]

    matches = []
    for item in users.values():
        haystack = " ".join([item.get("id", ""), item.get("name", ""), item.get("email", "")]).lower()
        if lowered and lowered in haystack:
            matches.append(item)
    if not matches:
        raise ValueError(f"Nutzer nicht gefunden oder hat keine Aufgaben: {user}")
    if len(matches) > 1:
        labels = [_user_label(match) for match in matches]
        raise ValueError(f"Nutzerangabe ist mehrdeutig. Bitte user_id nutzen. Treffer: {labels}")
    return matches[0]


class Tools:
    async def task_admin_status(
        self,
        include_user_breakdown: bool = False,
        completed_older_than_days: int = 180,
        __user__: dict = None,
    ) -> str:
        """
        Zeigt Admin-Kennzahlen zur zentralen Aufgaben-Datenbank.

        :param include_user_breakdown: Wenn true, Statuszaehler je user_id ausgeben.
        :param completed_older_than_days: Schwelle fuer alte erledigte Aufgaben.
        """
        try:
            _require_admin(__user__)
            exists = DB_PATH.exists()
            if not exists:
                return _json({"ok": True, "db_path": str(DB_PATH), "db_exists": False, "note": "Noch keine Aufgaben-DB vorhanden."})

            cutoff = int(time.time()) - max(1, int(completed_older_than_days or 180)) * 86400
            with closing(_connect_existing()) as con:
                if not _table_exists(con):
                    return _json({"ok": True, "db_path": str(DB_PATH), "db_exists": True, "tasks_table_exists": False})

                total = int(con.execute("select count(*) from tasks").fetchone()[0])
                users = int(con.execute("select count(distinct user_id) from tasks").fetchone()[0])
                by_status = {
                    row["status"]: int(row["count"])
                    for row in con.execute("select status, count(*) as count from tasks group by status").fetchall()
                }
                old_completed = int(
                    con.execute(
                        "select count(*) from tasks where status = 'completed' and coalesce(completed_at, updated_at, created_at) < ?",
                        (cutoff,),
                    ).fetchone()[0]
                )
                newest_updated_at = con.execute("select max(updated_at) from tasks").fetchone()[0]

                result: dict[str, Any] = {
                    "ok": True,
                    "db_path": str(DB_PATH),
                    "db_exists": True,
                    "db_size_bytes": DB_PATH.stat().st_size,
                    "tasks_total": total,
                    "users_with_tasks": users,
                    "by_status": by_status,
                    "completed_older_than_days": int(completed_older_than_days or 180),
                    "old_completed_candidates": old_completed,
                    "newest_updated_at": int(newest_updated_at) if newest_updated_at else None,
                }
                if include_user_breakdown:
                    result["by_user"] = _build_user_breakdown(con)

            return _json(result)
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    async def task_admin_list_user_tasks(
        self,
        user: str = "",
        user_index: int = 0,
        status: str = "open",
        limit: int = 50,
        __user__: dict = None,
    ) -> str:
        """
        Listet echte Aufgaben eines bestimmten Nutzers. Nur fuer OpenWebUI-Admins.

        :param user: user_id, Name, E-Mail oder "Nutzer 1" aus task_admin_status.
        :param user_index: Optionaler Index aus task_admin_status by_user.
        :param status: Optional open, in_progress, completed, cancelled oder leer fuer alle.
        :param limit: Maximale Anzahl Aufgaben.
        """
        try:
            _require_admin(__user__)
            if not DB_PATH.exists():
                return _json({"ok": True, "db_exists": False, "tasks": []})
            limit = max(1, min(int(limit or 50), 200))
            status = str(status or "").strip()
            with closing(_connect_existing()) as con:
                if not _table_exists(con):
                    return _json({"ok": True, "tasks_table_exists": False, "tasks": []})
                target_user = _resolve_user(con, user, int(user_index or 0))
                where = ["user_id = ?"]
                params: list[Any] = [target_user["id"]]
                if status:
                    where.append("status = ?")
                    params.append(status)
                params.append(limit)
                rows = con.execute(
                    "select * from tasks where "
                    + " and ".join(where)
                    + " order by created_at asc, rowid asc limit ?",
                    params,
                ).fetchall()
            return _json(
                {
                    "ok": True,
                    "user": {
                        "id": target_user["id"],
                        "name": target_user.get("name", ""),
                        "email": target_user.get("email", ""),
                        "role": target_user.get("role", ""),
                        "label": _user_label(target_user),
                    },
                    "status_filter": status,
                    "count": len(rows),
                    "tasks": [_row_to_task(row) for row in rows],
                }
            )
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    async def task_admin_cleanup_completed(
        self,
        older_than_days: int = 180,
        dry_run: bool = True,
        max_delete: int = 1000,
        __user__: dict = None,
    ) -> str:
        """
        Bereinigt alte erledigte Aufgaben. Standard ist Dry-Run.

        :param older_than_days: Nur erledigte Aufgaben aelter als diese Anzahl Tage.
        :param dry_run: True = nur zaehlen, False = loeschen.
        :param max_delete: Sicherheitslimit fuer geloeschte Aufgaben.
        """
        try:
            _require_admin(__user__)
            if not DB_PATH.exists():
                return _json({"ok": True, "db_exists": False, "deleted": 0, "candidates": 0})

            older_than_days = max(1, int(older_than_days or 180))
            max_delete = max(1, min(int(max_delete or 1000), 10000))
            cutoff = int(time.time()) - older_than_days * 86400
            with closing(_connect_existing()) as con:
                if not _table_exists(con):
                    return _json({"ok": True, "tasks_table_exists": False, "deleted": 0, "candidates": 0})
                candidates = [
                    row["id"]
                    for row in con.execute(
                        """
                        select id from tasks
                        where status = 'completed' and coalesce(completed_at, updated_at, created_at) < ?
                        order by coalesce(completed_at, updated_at, created_at) asc
                        limit ?
                        """,
                        (cutoff, max_delete),
                    ).fetchall()
                ]
                deleted = 0
                if not dry_run and candidates:
                    con.executemany("delete from tasks where id = ?", [(task_id,) for task_id in candidates])
                    deleted = len(candidates)
                    con.commit()

            return _json(
                {
                    "ok": True,
                    "dry_run": bool(dry_run),
                    "older_than_days": older_than_days,
                    "max_delete": max_delete,
                    "candidates": len(candidates),
                    "deleted": deleted,
                    "sample_task_ids": candidates[:20],
                }
            )
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})
