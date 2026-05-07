"""
title: KAHLE Tasks
author: local
version: 0.1.0
description: Persistente persoenliche Aufgaben fuer KAHLE-Vinci, sichtbar und steuerbar per Chat.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any


DB_PATH = Path(os.getenv("KAHLE_TASKS_DB_PATH", "/app/backend/data/kahle_vinci_tasks.db"))
VALID_STATUSES = {"open", "in_progress", "completed", "cancelled"}
VALID_PRIORITIES = {"low", "normal", "high", "urgent"}


def _now() -> int:
    return int(time.time())


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _user_id(__user__: dict | None) -> str:
    if isinstance(__user__, dict):
        value = str(__user__.get("id") or "").strip()
        if value:
            return value
    raise PermissionError(
        "OpenWebUI user_id fehlt. Aufgaben werden nicht gespeichert, wenn sie keinem eindeutigen Nutzer zugeordnet werden koennen."
    )


def _normalize_status(status: str) -> str:
    value = str(status or "open").strip().lower()
    if value in {"pending", "todo", "offen"}:
        return "open"
    if value in {"done", "erledigt"}:
        return "completed"
    if value not in VALID_STATUSES:
        raise ValueError(f"ungueltiger Status: {status}. Erlaubt: open, in_progress, completed, cancelled")
    return value


def _normalize_priority(priority: str) -> str:
    value = str(priority or "normal").strip().lower()
    if value in {"mittel", "medium"}:
        return "normal"
    if value in {"hoch"}:
        return "high"
    if value in {"niedrig"}:
        return "low"
    if value not in VALID_PRIORITIES:
        raise ValueError(f"ungueltige Prioritaet: {priority}. Erlaubt: low, normal, high, urgent")
    return value


def _clean_text(value: str, max_len: int = 8000) -> str:
    text = str(value or "").strip()
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(
        """
        create table if not exists tasks (
            id text primary key,
            user_id text not null,
            title text not null,
            description text not null default '',
            status text not null default 'open',
            priority text not null default 'normal',
            due_date text not null default '',
            source_chat_id text not null default '',
            source_message_id text not null default '',
            created_at integer not null,
            updated_at integer not null,
            completed_at integer
        )
        """
    )
    con.execute("create index if not exists idx_tasks_user_status on tasks(user_id, status)")
    con.execute("create index if not exists idx_tasks_user_due on tasks(user_id, due_date)")
    return con


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in ("created_at", "updated_at", "completed_at"):
        if data.get(key) is None:
            continue
        data[key] = int(data[key])
    return data


def _get_task(con: sqlite3.Connection, user_id: str, task_id: str) -> sqlite3.Row:
    row = con.execute("select * from tasks where id = ? and user_id = ?", (task_id, user_id)).fetchone()
    if not row:
        raise ValueError(f"Aufgabe nicht gefunden: {task_id}")
    return row


def _insert_task(
    con: sqlite3.Connection,
    user_id: str,
    title: str,
    description: str = "",
    due_date: str = "",
    priority: str = "normal",
    status: str = "open",
    source_chat_id: str = "",
    source_message_id: str = "",
) -> dict[str, Any]:
    title = _clean_text(title, 240)
    if not title:
        raise ValueError("title darf nicht leer sein")

    status = _normalize_status(status)
    priority = _normalize_priority(priority)
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    now = _now()
    completed_at = now if status == "completed" else None
    con.execute(
        """
        insert into tasks (
            id, user_id, title, description, status, priority, due_date,
            source_chat_id, source_message_id, created_at, updated_at, completed_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            user_id,
            title,
            _clean_text(description),
            status,
            priority,
            _clean_text(due_date, 80),
            _clean_text(source_chat_id, 120),
            _clean_text(source_message_id, 120),
            now,
            now,
            completed_at,
        ),
    )
    return _row_to_dict(_get_task(con, user_id, task_id))


class Tools:
    async def kv_task_create(
        self,
        title: str,
        description: str = "",
        due_date: str = "",
        priority: str = "normal",
        __chat_id__: str = "",
        __message_id__: str = "",
        __user__: dict = None,
    ) -> str:
        """
        Erstellt eine persistente persoenliche Aufgabe fuer den aktuellen Nutzer.

        :param title: Kurzer, eindeutiger Aufgabentitel.
        :param description: Optionaler Kontext oder naechster Schritt.
        :param due_date: Optionales Faelligkeitsdatum, bevorzugt YYYY-MM-DD.
        :param priority: low, normal, high oder urgent.
        """
        try:
            user_id = _user_id(__user__)
            with closing(_connect()) as con:
                task = _insert_task(con, user_id, title, description, due_date, priority, "open", __chat_id__, __message_id__)
                con.commit()
            return _json({"ok": True, "task": task})
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    async def kv_tasks_create_many(
        self,
        tasks_json: str,
        __chat_id__: str = "",
        __message_id__: str = "",
        __user__: dict = None,
    ) -> str:
        """
        Erstellt mehrere persistente persoenliche Aufgaben in einem Aufruf.

        :param tasks_json: JSON-Liste mit Objekten, z. B. [{"title":"Recherche","description":"...","due_date":"2026-05-08","priority":"high"}].
        """
        try:
            items = json.loads(tasks_json)
            if not isinstance(items, list):
                raise ValueError("tasks_json muss eine JSON-Liste sein")
            created = []
            user_id = _user_id(__user__)
            with closing(_connect()) as con:
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    created.append(
                        _insert_task(
                            con,
                            user_id,
                            str(item.get("title") or item.get("content") or ""),
                            str(item.get("description") or ""),
                            str(item.get("due_date") or ""),
                            str(item.get("priority") or "normal"),
                            str(item.get("status") or "open"),
                            __chat_id__,
                            __message_id__,
                        )
                    )
                con.commit()
            return _json({"ok": True, "created": created, "count": len(created)})
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    async def kv_tasks_list(
        self,
        status: str = "",
        include_completed: bool = False,
        limit: int = 25,
        __user__: dict = None,
    ) -> str:
        """
        Listet die persistenten Aufgaben des aktuellen Nutzers.

        :param status: Optional: open, in_progress, completed oder cancelled.
        :param include_completed: Wenn true, abgeschlossene Aufgaben mit anzeigen.
        :param limit: Maximale Anzahl, Standard 25.
        """
        try:
            user_id = _user_id(__user__)
            limit = max(1, min(int(limit or 25), 100))
            where = ["user_id = ?"]
            params: list[Any] = [user_id]
            if status:
                where.append("status = ?")
                params.append(_normalize_status(status))
            elif not include_completed:
                where.append("status != 'completed'")
            query = (
                "select * from tasks where "
                + " and ".join(where)
                + " order by case priority when 'urgent' then 0 when 'high' then 1 when 'normal' then 2 else 3 end, "
                + "case when due_date = '' then 1 else 0 end, due_date asc, created_at desc limit ?"
            )
            params.append(limit)
            with closing(_connect()) as con:
                tasks = [_row_to_dict(row) for row in con.execute(query, params).fetchall()]
            return _json({"ok": True, "tasks": tasks, "count": len(tasks)})
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    async def kv_task_update(
        self,
        task_id: str,
        title: str = "",
        description: str = "",
        due_date: str = "",
        priority: str = "",
        status: str = "",
        __user__: dict = None,
    ) -> str:
        """
        Aktualisiert eine bestehende Aufgabe.

        :param task_id: ID der Aufgabe, z. B. task_ab12cd34ef56.
        :param title: Optional neuer Titel.
        :param description: Optional neue Beschreibung.
        :param due_date: Optional neues Faelligkeitsdatum. Leer lassen, wenn unveraendert.
        :param priority: Optional low, normal, high oder urgent.
        :param status: Optional open, in_progress, completed oder cancelled.
        """
        try:
            user_id = _user_id(__user__)
            updates: list[str] = []
            params: list[Any] = []
            if title:
                updates.append("title = ?")
                params.append(_clean_text(title, 240))
            if description:
                updates.append("description = ?")
                params.append(_clean_text(description))
            if due_date:
                updates.append("due_date = ?")
                params.append(_clean_text(due_date, 80))
            if priority:
                updates.append("priority = ?")
                params.append(_normalize_priority(priority))
            if status:
                normalized = _normalize_status(status)
                updates.append("status = ?")
                params.append(normalized)
                updates.append("completed_at = ?")
                params.append(_now() if normalized == "completed" else None)
            if not updates:
                raise ValueError("Keine Aenderung angegeben")
            updates.append("updated_at = ?")
            params.append(_now())
            params.extend([task_id, user_id])
            with closing(_connect()) as con:
                _get_task(con, user_id, task_id)
                con.execute(f"update tasks set {', '.join(updates)} where id = ? and user_id = ?", params)
                task = _row_to_dict(_get_task(con, user_id, task_id))
                con.commit()
            return _json({"ok": True, "task": task})
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    async def kv_task_complete(self, task_id: str, __user__: dict = None) -> str:
        """
        Markiert eine Aufgabe als erledigt.

        :param task_id: ID der Aufgabe, z. B. task_ab12cd34ef56.
        """
        return await self.kv_task_update(task_id=task_id, status="completed", __user__=__user__)

    async def kv_task_delete(self, task_id: str, __user__: dict = None) -> str:
        """
        Loescht eine Aufgabe des aktuellen Nutzers.

        :param task_id: ID der Aufgabe, z. B. task_ab12cd34ef56.
        """
        try:
            user_id = _user_id(__user__)
            with closing(_connect()) as con:
                task = _row_to_dict(_get_task(con, user_id, task_id))
                con.execute("delete from tasks where id = ? and user_id = ?", (task_id, user_id))
                con.commit()
            return _json({"ok": True, "deleted": task})
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})
