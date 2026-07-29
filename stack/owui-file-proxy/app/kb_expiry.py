from __future__ import annotations

import hashlib
import re
import sqlite3
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any


DEFAULT_COLLECTIONS = ("kahleallgemein", "kahlekontext", "kahlerichtlinien")
SUPPORTED_EXTENSIONS = (".md", ".txt", ".csv", ".pdf", ".docx")
SYSTEM_SOURCE = "system:kb-expiry"
DATE_KEYS = ("valid_until", "gueltig_bis", "gültig_bis")
FILENAME_DATE_RE = re.compile(
    r"(?:gueltig|gultig|valid)[\s._-]*(?:bis|until)[\s._:-]*"
    r"(?P<date>\d{4}[-_.]\d{2}[-_.]\d{2}|\d{2}[-_.]\d{2}[-_.]\d{4})",
    re.IGNORECASE,
)


def _ascii_fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char)).lower()


def _scalar(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text[0:1] in {'"', "'"} and text[-1:] == text[0]:
        return text[1:-1].strip()
    return re.split(r"\s+#", text, maxsplit=1)[0].strip()


def _frontmatter(path: Path) -> dict[str, str]:
    if path.suffix.lower() != ".md":
        return {}
    try:
        text = path.read_bytes()[:32768].decode("utf-8-sig", errors="replace")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = re.search(r"^---\s*$", text[3:], flags=re.MULTILINE)
    if not end:
        return {}
    block = text[3 : 3 + end.start()]
    result: dict[str, str] = {}
    for line in block.splitlines():
        match = re.match(r"^\s*([A-Za-z0-9_äöüÄÖÜß-]+)\s*:\s*(.*?)\s*$", line)
        if not match:
            continue
        key = match.group(1).strip().lower().replace("-", "_")
        result[key] = _scalar(match.group(2))
    return result


def _bool_value(value: str, default: bool = True) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return default
    return normalized not in {"false", "no", "0", "off", "nein"}


def _parse_date(value: str) -> date | None:
    raw = str(value or "").strip().replace("_", "-").replace(".", "-")
    for pattern in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    return None


def _filename_date(path: Path) -> date | None:
    match = FILENAME_DATE_RE.search(_ascii_fold(path.stem))
    return _parse_date(match.group("date")) if match else None


def _metadata_date(metadata: dict[str, str]) -> date | None:
    for key in DATE_KEYS:
        parsed = _parse_date(metadata.get(key, ""))
        if parsed:
            return parsed
    return None


def _notify_days(metadata: dict[str, str], default: int) -> int:
    try:
        value = int(metadata.get("notify_before_days") or default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, 365))


def _document_title(path: Path, metadata: dict[str, str]) -> str:
    return metadata.get("title") or path.stem.replace("_", " ").replace("-", " ").strip()


def scan_expiring_documents(
    kb_root: Path,
    today: date | None = None,
    default_notify_days: int = 14,
    collections: tuple[str, ...] = DEFAULT_COLLECTIONS,
) -> list[dict[str, Any]]:
    reference_date = today or date.today()
    documents: list[dict[str, Any]] = []
    for collection in collections:
        collection_root = kb_root / collection
        if not collection_root.exists():
            continue
        for path in sorted(collection_root.rglob("*")):
            if (
                not path.is_file()
                or path.name.startswith(".")
                or path.name.startswith("~$")
                or path.suffix.lower() not in SUPPORTED_EXTENSIONS
            ):
                continue
            metadata = _frontmatter(path)
            if not _bool_value(metadata.get("rag_index", ""), default=True):
                continue
            if metadata.get("status", "active").strip().lower() not in {"", "active", "aktiv", "published"}:
                continue
            valid_until = _metadata_date(metadata) or _filename_date(path)
            if not valid_until:
                continue
            notify_days = _notify_days(metadata, default_notify_days)
            days_remaining = (valid_until - reference_date).days
            if days_remaining > notify_days:
                continue
            rel_path = path.relative_to(collection_root).as_posix()
            doc_id = metadata.get("document_id") or f"{collection}/{rel_path}"
            if days_remaining < 0:
                state = "expired"
            elif days_remaining == 0:
                state = "expires_today"
            else:
                state = "due_soon"
            documents.append(
                {
                    "collection": collection,
                    "source_path": rel_path,
                    "doc_id": doc_id,
                    "title": _document_title(path, metadata),
                    "owner_name": metadata.get("owner_name") or metadata.get("owner") or "",
                    "owner_email": metadata.get("owner_email") or "",
                    "valid_until": valid_until.isoformat(),
                    "notify_before_days": notify_days,
                    "days_remaining": days_remaining,
                    "state": state,
                    "mtime": int(path.stat().st_mtime),
                }
            )
    return sorted(
        documents,
        key=lambda item: (int(item["days_remaining"]), str(item["collection"]), str(item["source_path"])),
    )


def _ensure_tasks_table(con: sqlite3.Connection) -> None:
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


def _admin_users(webui_db_path: Path) -> list[dict[str, str]]:
    if not webui_db_path.exists():
        return []
    con = sqlite3.connect(webui_db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "select id, name, email from user where lower(coalesce(role, '')) = 'admin' order by id"
        ).fetchall()
        return [
            {
                "id": str(row["id"] or ""),
                "name": str(row["name"] or ""),
                "email": str(row["email"] or ""),
            }
            for row in rows
            if row["id"]
        ]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _task_id(user_id: str, doc_id: str) -> str:
    digest = hashlib.sha256(f"{user_id}\n{doc_id}".encode("utf-8")).hexdigest()[:24]
    return f"kbexp_{digest}"


def _priority(days_remaining: int) -> str:
    if days_remaining <= 0:
        return "urgent"
    if days_remaining <= 7:
        return "high"
    return "normal"


def _task_description(document: dict[str, Any]) -> str:
    remaining = int(document["days_remaining"])
    if remaining < 0:
        timing = f"seit {abs(remaining)} Tag(en) abgelaufen"
    elif remaining == 0:
        timing = "läuft heute ab"
    else:
        timing = f"läuft in {remaining} Tag(en) ab"
    lines = [
        f"Die Wissensdatei „{document['title']}“ {timing}.",
        f"Collection: {document['collection']}",
        f"Datei: {document['source_path']}",
        f"Gültig bis: {document['valid_until']}",
        "Nächster Schritt: Inhalt prüfen und Gültigkeit aktualisieren oder rag_index auf false setzen.",
    ]
    if document.get("owner_name"):
        lines.append(f"Verantwortlich: {document['owner_name']}")
    if document.get("owner_email"):
        lines.append(f"Kontakt: {document['owner_email']}")
    return "\n".join(lines)


def sync_expiry_tasks(
    kb_root: Path,
    tasks_db_path: Path,
    webui_db_path: Path,
    today: date | None = None,
    default_notify_days: int = 14,
    dry_run: bool = True,
) -> dict[str, Any]:
    documents = scan_expiring_documents(
        kb_root=kb_root,
        today=today,
        default_notify_days=default_notify_days,
    )
    admins = _admin_users(webui_db_path)
    expected_task_ids = {
        _task_id(admin["id"], str(document["doc_id"]))
        for admin in admins
        for document in documents
    }
    result: dict[str, Any] = {
        "ok": True,
        "dry_run": bool(dry_run),
        "today": (today or date.today()).isoformat(),
        "admins": [{"id": item["id"], "name": item["name"], "email": item["email"]} for item in admins],
        "admin_count": len(admins),
        "expiring_count": len(documents),
        "documents": documents,
        "created": 0,
        "updated": 0,
        "cancelled": 0,
    }
    if dry_run or not admins:
        return result

    tasks_db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(tasks_db_path, timeout=30)
    con.row_factory = sqlite3.Row
    now = int(time.time())
    try:
        _ensure_tasks_table(con)
        for admin in admins:
            for document in documents:
                task_id = _task_id(admin["id"], str(document["doc_id"]))
                existing = con.execute("select id from tasks where id = ?", (task_id,)).fetchone()
                values = (
                    admin["id"],
                    f"Wissensdatei prüfen: {document['title']}",
                    _task_description(document),
                    "open",
                    _priority(int(document["days_remaining"])),
                    document["valid_until"],
                    SYSTEM_SOURCE,
                    str(document["doc_id"]),
                    now,
                    None,
                )
                if existing:
                    con.execute(
                        """
                        update tasks
                        set user_id = ?, title = ?, description = ?, status = ?, priority = ?,
                            due_date = ?, source_chat_id = ?, source_message_id = ?,
                            updated_at = ?, completed_at = ?
                        where id = ?
                        """,
                        (*values, task_id),
                    )
                    result["updated"] += 1
                else:
                    con.execute(
                        """
                        insert into tasks (
                            id, user_id, title, description, status, priority, due_date,
                            source_chat_id, source_message_id, created_at, updated_at, completed_at
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            task_id,
                            admin["id"],
                            f"Wissensdatei prüfen: {document['title']}",
                            _task_description(document),
                            "open",
                            _priority(int(document["days_remaining"])),
                            document["valid_until"],
                            SYSTEM_SOURCE,
                            str(document["doc_id"]),
                            now,
                            now,
                            None,
                        ),
                    )
                    result["created"] += 1

        stale_rows = con.execute(
            "select id from tasks where source_chat_id = ? and status in ('open', 'in_progress')",
            (SYSTEM_SOURCE,),
        ).fetchall()
        stale_ids = [str(row["id"]) for row in stale_rows if str(row["id"]) not in expected_task_ids]
        if stale_ids:
            con.executemany(
                "update tasks set status = 'cancelled', updated_at = ?, completed_at = null where id = ?",
                [(now, task_id) for task_id in stale_ids],
            )
            result["cancelled"] = len(stale_ids)
        con.commit()
        return result
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
