"""Files a file tool call may read: those of the chat that makes the call.

Open WebUI sends the chat and user of every tool-server call as connection
headers interpolated from its own request metadata ({{CHAT_ID}}, {{USER_ID}}),
never from model arguments. The allowed files are the chat's attachments
(webui.db chat_file) and the files the proxy generated for that chat (download
link manifests carry the chat). Anything else under the uploads root, other
users' files included, is not resolvable.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

CHAT_ID_HEADER = "x-kahle-chat-id"
USER_ID_HEADER = "x-kahle-user-id"


@dataclass(frozen=True)
class ChatScope:
    chat_id: str
    user_id: str

    @property
    def temporary(self) -> bool:
        return self.chat_id.startswith("local:")


def scope_from_headers(chat_id: object, user_id: object) -> ChatScope | None:
    chat = str(chat_id or "").strip()
    user = str(user_id or "").strip()
    # An uninterpolated template means Open WebUI had no chat for this call.
    if not chat or not user or "{{" in chat or "{{" in user:
        return None
    return ChatScope(chat, user)


def manifest_scope_fields(scope: ChatScope | None) -> dict[str, str]:
    return {"chat_id": scope.chat_id, "user_id": scope.user_id} if scope else {}


def _rel_to_root(upload_root: Path, stored_path: str) -> str | None:
    raw = str(stored_path or "").replace("\\", "/")
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = upload_root / raw.split("/")[-1]
    try:
        return candidate.resolve().relative_to(upload_root.resolve()).as_posix()
    except ValueError:
        return None


def _attachment_paths(upload_root: Path, db_path: Path, scope: ChatScope) -> set[str]:
    if not db_path.is_file():
        return set()
    if scope.temporary:
        # Temporary chats are not stored, so chat_file has no rows for them.
        # They may use the user's own uploads, never another user's.
        query = "select f.path from file f where f.user_id = ?"
        params: tuple[str, ...] = (scope.user_id,)
    else:
        query = (
            "select f.path from chat_file cf"
            " join chat c on c.id = cf.chat_id"
            " join file f on f.id = cf.file_id"
            " where cf.chat_id = ? and c.user_id = ? and f.user_id = ?"
        )
        params = (scope.chat_id, scope.user_id, scope.user_id)
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=10.0)
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return set()
    return {rel for (stored,) in rows if (rel := _rel_to_root(upload_root, stored))}


def _generated_paths(upload_root: Path, scope: ChatScope, output_subdir: str, now: int) -> set[str]:
    prefix = output_subdir.strip("/") + "/"
    found: set[str] = set()
    for manifest_path in (upload_root / ".download-links").glob("*.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            exp = int(manifest.get("exp"))
        except Exception:
            continue
        if manifest.get("chat_id") != scope.chat_id or manifest.get("user_id") != scope.user_id or exp < now:
            continue
        rel = str(manifest.get("rel") or "").replace("\\", "/").lstrip("/")
        if rel.startswith(prefix) and not any(p in ("", ".", "..") for p in rel[len(prefix):].split("/")):
            found.add(rel)
    return found


def allowed_rel_paths(
    upload_root: Path,
    db_path: Path,
    scope: ChatScope,
    output_subdir: str,
    now: int | None = None,
) -> set[str]:
    """Relative paths (under upload_root) this chat may read, fail-closed."""
    current = int(time.time() if now is None else now)
    return _attachment_paths(upload_root, db_path, scope) | _generated_paths(
        upload_root, scope, output_subdir, current
    )
