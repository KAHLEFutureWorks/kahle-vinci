"""
title: KAHLE Tasks
author: local
version: 0.1.0
description: Persistente persoenliche Aufgaben fuer KAHLE-Vinci, sichtbar und steuerbar per Chat.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DB_PATH = Path(os.getenv("KAHLE_TASKS_DB_PATH", "/app/backend/data/kahle_vinci_tasks.db"))
VALID_STATUSES = {"open", "in_progress", "completed", "cancelled"}
VALID_PRIORITIES = {"low", "normal", "high", "urgent"}
try:
    LOCAL_TZ = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover - Windows test env may not have tzdata
    LOCAL_TZ = timezone(timedelta(hours=2))


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


def _decode_chat_content(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            decoded = json.loads(text)
            if isinstance(decoded, str):
                return decoded.strip()
        except Exception:
            pass
    return text


def _title_lookup_key(value: str) -> str:
    text = _clean_text(value, 240).lower()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "é": "e",
        "è": "e",
        "á": "a",
        "à": "a",
        "ó": "o",
        "ò": "o",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _title_fuzzy_key(value: str) -> str:
    return re.sub(r"[aeiou ]+", "", _title_lookup_key(value))


def _today() -> date:
    override = os.getenv("KAHLE_TASKS_TODAY", "").strip()
    if override:
        try:
            return date.fromisoformat(override)
        except ValueError:
            pass
    return datetime.now(LOCAL_TZ).date()


def _display_ts(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(int(value), LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _latest_user_message(chat_id: str | None) -> str:
    chat_id = (chat_id or "").strip()
    db_path = Path(os.getenv("OWUI_DB_PATH", "/app/backend/data/webui.db"))
    if not chat_id or not db_path.exists():
        return ""
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        row = con.execute(
            """
            select content
            from chat_message
            where chat_id = ? and role = 'user'
            order by coalesce(created_at, 0) desc, coalesce(updated_at, 0) desc
            limit 1
            """,
            (chat_id,),
        ).fetchone()
        return _decode_chat_content(row["content"]) if row else ""
    except Exception:
        return ""
    finally:
        try:
            con.close()
        except Exception:
            pass


def _quoted_task_title(text: str) -> str:
    text = str(text or "")
    match = re.search(r'["\u201c\u201d\u201e](.+?)["\u201c\u201d]', text)
    if match:
        return _clean_text(match.group(1), 240)
    match = re.search(
        r"(?:aufgabe|task)\s+(.+?)\s+(?:auf|als|mit|und|erledigt|abschliessen|abschlie\u00dfen|$)",
        text,
        flags=re.IGNORECASE,
    )
    return _clean_text(match.group(1), 240) if match else ""


def _infer_task_update_from_text(text: str) -> dict[str, str]:
    text = str(text or "")
    lower = text.lower()
    inferred: dict[str, str] = {}

    title = _quoted_task_title(text)
    if title:
        inferred["lookup_title"] = title

    if "dringend" in lower or "urgent" in lower:
        inferred["priority"] = "urgent"
    elif "hoch" in lower or "high" in lower:
        inferred["priority"] = "high"
    elif "niedrig" in lower or "low" in lower:
        inferred["priority"] = "low"
    elif "normal" in lower:
        inferred["priority"] = "normal"

    desc_match = re.search(
        r"(?:ergaenze|erg(?:a|\u00e4)nze|notiz|beschreibung)\s*:?\s*(.+)$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if desc_match:
        inferred["description"] = _clean_text(desc_match.group(1).strip(" ."), 8000)

    if "erledigt" in lower or "abgeschlossen" in lower or "abschliessen" in lower or "abschlie\u00dfen" in lower:
        inferred["status"] = "completed"

    if "uebermorgen" in lower or "\u00fcbermorgen" in lower or "morgen" in lower or "heute" in lower:
        inferred["due_date"] = _normalize_due_date("", text)

    return inferred


def _normalize_due_date(due_date: str, source_text: str = "") -> str:
    text = (source_text or "").lower()
    base = _today()
    if "übermorgen" in text or "uebermorgen" in text:
        return (base + timedelta(days=2)).isoformat()
    if "morgen" in text:
        return (base + timedelta(days=1)).isoformat()
    if "heute" in text:
        return base.isoformat()
    return _clean_text(due_date, 80)


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
    data["created_at_display"] = _display_ts(data.get("created_at"))
    data["updated_at_display"] = _display_ts(data.get("updated_at"))
    data["completed_at_display"] = _display_ts(data.get("completed_at"))
    return data


def _get_task(con: sqlite3.Connection, user_id: str, task_id: str) -> sqlite3.Row:
    row = con.execute("select * from tasks where id = ? and user_id = ?", (task_id, user_id)).fetchone()
    if not row:
        raise ValueError(f"Aufgabe nicht gefunden: {task_id}")
    return row


def _resolve_task(con: sqlite3.Connection, user_id: str, task_id: str = "", title: str = "") -> sqlite3.Row:
    task_id = _clean_text(task_id, 120)
    title = _clean_text(title, 240)
    if task_id:
        return _get_task(con, user_id, task_id)
    if not title:
        raise ValueError("task_id oder eindeutiger Titel fehlt")

    title_lower = title.lower()
    rows = con.execute(
        """
        select *
        from tasks
        where user_id = ?
          and status != 'completed'
          and lower(title) = ?
        order by updated_at desc
        """,
        (user_id, title_lower),
    ).fetchall()
    if not rows:
        rows = con.execute(
            """
            select *
            from tasks
            where user_id = ?
              and status != 'completed'
              and lower(title) like ?
            order by updated_at desc
            """,
            (user_id, f"%{title_lower}%"),
        ).fetchall()
    if len(rows) == 1:
        return rows[0]
    if not rows:
        title_key = _title_lookup_key(title)
        candidates = con.execute(
            """
            select *
            from tasks
            where user_id = ?
              and status != 'completed'
            order by updated_at desc
            """,
            (user_id,),
        ).fetchall()
        title_fuzzy = _title_fuzzy_key(title)
        rows = []
        for row in candidates:
            row_key = _title_lookup_key(str(row["title"]))
            row_fuzzy = _title_fuzzy_key(str(row["title"]))
            if not title_key:
                continue
            if row_key == title_key or title_key in row_key or row_key in title_key:
                rows.append(row)
                continue
            if title_fuzzy and row_fuzzy and (row_fuzzy == title_fuzzy or title_fuzzy in row_fuzzy or row_fuzzy in title_fuzzy):
                rows.append(row)
        if len(rows) == 1:
            return rows[0]
    if not rows:
        raise ValueError(f"Keine offene Aufgabe mit diesem Titel gefunden: {title}")
    matches = ", ".join(f"{row['id']} ({row['title']})" for row in rows[:5])
    raise ValueError(f"Titel ist nicht eindeutig. Bitte task_id nutzen. Treffer: {matches}")


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
    source_text: str = "",
) -> dict[str, Any]:
    title = _clean_text(title, 240)
    if not title:
        raise ValueError("title darf nicht leer sein")

    status = _normalize_status(status)
    priority = _normalize_priority(priority)
    due_date = _normalize_due_date(due_date, source_text)
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
            due_date,
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
            source_text = _latest_user_message(__chat_id__)
            with closing(_connect()) as con:
                task = _insert_task(
                    con,
                    user_id,
                    title,
                    description,
                    due_date,
                    priority,
                    "open",
                    __chat_id__,
                    __message_id__,
                    source_text,
                )
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
            source_text = _latest_user_message(__chat_id__)
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
                            source_text,
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
        task_id: str = "",
        title: str = "",
        task_title: str = "",
        lookup_title: str = "",
        new_title: str = "",
        description: str = "",
        due_date: str = "",
        priority: str = "",
        status: str = "",
        __chat_id__: str = "",
        __user__: dict = None,
    ) -> str:
        """
        Aktualisiert eine bestehende Aufgabe.

        :param task_id: ID der Aufgabe, z. B. task_ab12cd34ef56. Optional, wenn task_title/title eindeutig ist.
        :param title: Eindeutiger aktueller Titel, wenn keine task_id bekannt ist.
        :param task_title: Alias fuer aktueller Titel.
        :param lookup_title: Alias fuer aktueller Titel.
        :param new_title: Optional neuer Titel.
        :param description: Optional neue Beschreibung.
        :param due_date: Optional neues Faelligkeitsdatum. Leer lassen, wenn unveraendert.
        :param priority: Optional low, normal, high oder urgent.
        :param status: Optional open, in_progress, completed oder cancelled.
        """
        try:
            user_id = _user_id(__user__)
            source_text = _latest_user_message(__chat_id__)
            if source_text:
                inferred = _infer_task_update_from_text(source_text)
                lookup_title = lookup_title or inferred.get("lookup_title", "")
                priority = priority or inferred.get("priority", "")
                description = description or inferred.get("description", "")
                due_date = due_date or inferred.get("due_date", "")
                status = status or inferred.get("status", "")
            lookup = lookup_title or task_title or (title if not task_id else "")
            updates: list[str] = []
            params: list[Any] = []
            if new_title or (title and task_id):
                updates.append("title = ?")
                params.append(_clean_text(new_title or title, 240))
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
            with closing(_connect()) as con:
                row = _resolve_task(con, user_id, task_id, lookup)
                resolved_id = str(row["id"])
                params.extend([resolved_id, user_id])
                con.execute(f"update tasks set {', '.join(updates)} where id = ? and user_id = ?", params)
                task = _row_to_dict(_get_task(con, user_id, resolved_id))
                con.commit()
            return _json({"ok": True, "task": task})
        except Exception as exc:
            return _json({"ok": False, "error": str(exc)})

    async def kv_task_complete(
        self,
        task_id: str = "",
        title: str = "",
        task_title: str = "",
        lookup_title: str = "",
        __chat_id__: str = "",
        __user__: dict = None,
    ) -> str:
        """
        Markiert eine Aufgabe als erledigt.

        :param task_id: ID der Aufgabe, z. B. task_ab12cd34ef56. Optional, wenn title eindeutig ist.
        :param title: Eindeutiger aktueller Titel, wenn keine task_id bekannt ist.
        """
        source_text = _latest_user_message(__chat_id__)
        if source_text and not (task_id or title or task_title or lookup_title):
            lookup_title = _infer_task_update_from_text(source_text).get("lookup_title", "")
        return await self.kv_task_update(
            task_id=task_id,
            title=title,
            task_title=task_title,
            lookup_title=lookup_title,
            status="completed",
            __chat_id__=__chat_id__,
            __user__=__user__,
        )

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
