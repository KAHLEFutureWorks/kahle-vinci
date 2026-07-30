from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import requests
from docx import Document
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from pypdf import PdfReader


APP_VERSION = "0.2.0"
SUPPORTED_EXTENSIONS = {".md", ".txt", ".csv", ".pdf", ".docx"}
EDITABLE_EXTENSIONS = {".md", ".txt", ".csv"}
KB_ROOT = Path(os.getenv("KB_ROOT", "/knowledgebases")).resolve()
KB_STATE_PATH = Path(os.getenv("KB_STATE_PATH", "/state/kb-sync-state.json")).resolve()
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/")
OPENWEBUI_URL = os.getenv("OPENWEBUI_URL", "http://open-webui:8080").rstrip("/")
KB_SYNC_URL = os.getenv("KB_SYNC_URL", "http://kb-sync:8093").rstrip("/")
IONOS_BASE_URL = os.getenv(
    "IONOS_OPENAI_BASE_URL", "https://openai.inference.de-txl.ionos.com/v1"
).rstrip("/")
IONOS_API_KEY = os.getenv("IONOS_API_KEY", "").strip()
EMBEDDING_MODEL = os.getenv("IONOS_EMBEDDING_MODEL", "BAAI/bge-m3").strip()
COLLECTIONS = tuple(
    item.strip()
    for item in os.getenv(
        "KB_ADMIN_COLLECTIONS", "kahleallgemein,kahlekontext,kahlerichtlinien"
    ).split(",")
    if item.strip()
)
COLLECTION_LABELS = {
    "kahleallgemein": "Allgemeines Wissen",
    "kahlekontext": "Standorte & Unternehmen",
    "kahlerichtlinien": "Richtlinien & Prozesse",
}
DEV_AUTH_BYPASS = os.getenv("KB_ADMIN_DEV_AUTH_BYPASS", "false").lower() == "true"
MAX_UPLOAD_BYTES = int(os.getenv("KB_ADMIN_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
TRASH_RETENTION_DAYS = max(1, int(os.getenv("KB_ADMIN_TRASH_RETENTION_DAYS", "30")))
MAINTENANCE_API_KEY = os.getenv("KB_ADMIN_MAINTENANCE_API_KEY", "").strip()
UNLOCK_CODE_HASH = os.getenv("KB_ADMIN_UNLOCK_CODE_HASH", "").strip()
UNLOCK_SESSION_SECRET = os.getenv("KB_ADMIN_UNLOCK_SESSION_SECRET", "").strip()
UNLOCK_TTL_SECONDS = max(300, int(os.getenv("KB_ADMIN_UNLOCK_TTL_SECONDS", "28800")))
UNLOCK_MAX_ATTEMPTS = max(1, int(os.getenv("KB_ADMIN_UNLOCK_MAX_ATTEMPTS", "5")))
UNLOCK_BLOCK_SECONDS = max(60, int(os.getenv("KB_ADMIN_UNLOCK_BLOCK_SECONDS", "900")))
UNLOCK_COOKIE = "kahle_vector_unlock"
UNLOCK_ENABLED = bool(
    UNLOCK_CODE_HASH.startswith("pbkdf2_sha256.") and len(UNLOCK_SESSION_SECRET) >= 43
)
_unlock_failures: dict[str, list[float]] = {}
_unlock_failures_lock = threading.Lock()
VERSIONS_ROOT = KB_ROOT / ".versions"
TRASH_ROOT = KB_ROOT / ".trash"
AUDIT_ROOT = KB_ROOT / ".admin"
AUDIT_PATH = AUDIT_ROOT / "audit.jsonl"


app = FastAPI(
    title="KAHLE Vector Admin API",
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None,
)


class SaveDocumentRequest(BaseModel):
    content: str = Field(..., max_length=2_000_000)


class MoveDocumentRequest(BaseModel):
    target_collection: str
    target_path: str


class RestoreVersionRequest(BaseModel):
    version_id: str


class CreateCollectionRequest(BaseModel):
    id: str = Field(..., min_length=2, max_length=48, pattern=r"^[a-z0-9][a-z0-9_-]+$")
    label: str = Field(..., min_length=2, max_length=80)


class UpdateCollectionRequest(BaseModel):
    label: str = Field(..., min_length=2, max_length=80)


class DeleteCollectionRequest(BaseModel):
    confirm_id: str


class PurgeCollectionRequest(BaseModel):
    confirm_id: str


class UnlockRequest(BaseModel):
    code: str = Field(..., min_length=8, max_length=256)


def _collection_names() -> tuple[str, ...]:
    discovered = {
        path.name
        for path in KB_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    } if KB_ROOT.exists() else set()
    return tuple(sorted(set(COLLECTIONS) | discovered))


def _collection_label(name: str) -> str:
    metadata_path = KB_ROOT / name / ".collection.json"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        label = str(payload.get("label") or "").strip()
        if label:
            return label
    except Exception:
        pass
    return COLLECTION_LABELS.get(name, name)


def _safe_collection(name: str) -> str:
    if name not in _collection_names():
        raise HTTPException(status_code=404, detail="unknown_collection")
    return name


def _safe_relative_path(raw: str, *, require_supported: bool = True) -> PurePosixPath:
    value = str(raw or "").replace("\\", "/").strip().lstrip("/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HTTPException(status_code=400, detail="invalid_relative_path")
    if any(part.startswith(".") for part in path.parts):
        raise HTTPException(status_code=400, detail="hidden_paths_not_allowed")
    if require_supported and path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported_file_type")
    return path


def _document_path(collection: str, relative_path: str, *, must_exist: bool = True) -> Path:
    collection = _safe_collection(collection)
    rel = _safe_relative_path(relative_path)
    root = (KB_ROOT / collection).resolve()
    candidate = (root / Path(*rel.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="path_outside_collection") from exc
    if must_exist and (not candidate.exists() or not candidate.is_file()):
        raise HTTPException(status_code=404, detail="document_not_found")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_preview(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in EDITABLE_EXTENSIONS:
        return _read_text(path)
    if suffix == ".pdf":
        pages: list[str] = []
        for index, page in enumerate(PdfReader(str(path)).pages[:8], start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"[Seite {index}]\n{text}")
        return "\n\n".join(pages)
    if suffix == ".docx":
        doc = Document(str(path))
        paragraphs = [paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text.strip()]
        return "\n\n".join(paragraphs[:300])
    return ""


def _frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    match = re.search(r"^---\s*$", text[3:], flags=re.MULTILINE)
    if not match:
        return {}
    result: dict[str, Any] = {}
    current_list: str | None = None
    for raw_line in text[3 : 3 + match.start()].splitlines():
        line = raw_line.rstrip()
        list_match = re.match(r"^\s*-\s*(.+?)\s*$", line)
        if list_match and current_list:
            result.setdefault(current_list, []).append(list_match.group(1).strip(" \"'"))
            continue
        field = re.match(r"^\s*([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$", line)
        if not field:
            current_list = None
            continue
        key = field.group(1).lower().replace("-", "_")
        value = field.group(2).strip()
        if not value:
            result[key] = []
            current_list = key
            continue
        current_list = None
        if value.startswith("[") and value.endswith("]"):
            result[key] = [
                item.strip().strip(" \"'") for item in value[1:-1].split(",") if item.strip()
            ]
        else:
            result[key] = value.strip(" \"'")
    return result


def _expiry_from_filename(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    patterns = (
        r"(?:gueltig|gultig)[\s_-]*bis[\s_:-]*(\d{4}-\d{2}-\d{2})",
        r"(?:gueltig|gultig)[\s_-]*bis[\s_:-]*(\d{2}\.\d{2}\.\d{4})",
    )
    for pattern in patterns:
        match = re.search(pattern, folded)
        if not match:
            continue
        raw = match.group(1)
        try:
            return (
                datetime.strptime(raw, "%Y-%m-%d")
                if "-" in raw
                else datetime.strptime(raw, "%d.%m.%Y")
            ).date().isoformat()
        except ValueError:
            return ""
    return ""


def _normalise_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _metadata(path: Path) -> dict[str, Any]:
    text = _read_text(path) if path.suffix.lower() in EDITABLE_EXTENSIONS else ""
    meta = _frontmatter(text)
    valid_until = _normalise_date(
        meta.get("valid_until") or meta.get("gueltig_bis") or meta.get("gültig_bis")
    ) or _expiry_from_filename(path.name)
    days_remaining: int | None = None
    try:
        notify_before_days = max(0, min(365, int(meta.get("notify_before_days") or 14)))
    except (TypeError, ValueError):
        notify_before_days = 14
    expiry_status = "none"
    if valid_until:
        days_remaining = (date.fromisoformat(valid_until) - date.today()).days
        if days_remaining < 0:
            expiry_status = "expired"
        elif days_remaining <= notify_before_days:
            expiry_status = "critical"
        elif days_remaining <= 30:
            expiry_status = "warning"
        else:
            expiry_status = "valid"
    rag_value = str(meta.get("rag_index", "true")).strip().lower()
    return {
        "title": str(meta.get("title") or path.stem).strip(),
        "document_id": str(meta.get("document_id") or "").strip(),
        "owner": str(meta.get("owner") or meta.get("owner_name") or "").strip(),
        "valid_until": valid_until,
        "days_remaining": days_remaining,
        "notify_before_days": notify_before_days,
        "expiry_status": expiry_status,
        "locations": meta.get("standorte") or meta.get("locations") or [],
        "tags": meta.get("tags") or [],
        "rag_index": rag_value not in {"false", "0", "no"},
    }


def _load_state() -> dict[str, Any]:
    try:
        payload = json.loads(KB_STATE_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _state_entry(state: dict[str, Any], collection: str, relative_path: str) -> dict[str, Any]:
    return (
        (((state.get("collections") or {}).get(collection) or {}).get("files") or {}).get(
            relative_path
        )
        or {}
    )


def _index_status(path: Path, entry: dict[str, Any], rag_index: bool) -> str:
    if not rag_index:
        return "excluded"
    if not entry:
        return "pending"
    try:
        return "current" if entry.get("sha256") == _sha256(path) else "pending"
    except OSError:
        return "error"


def _version_key(collection: str, relative_path: str) -> Path:
    encoded = hashlib.sha256(f"{collection}/{relative_path}".encode("utf-8")).hexdigest()[:20]
    return VERSIONS_ROOT / collection / encoded


def _create_version(path: Path, collection: str, relative_path: str, actor: dict[str, Any], action: str) -> str:
    if not path.exists():
        return ""
    version_dir = _version_key(collection, relative_path)
    version_dir.mkdir(parents=True, exist_ok=True)
    version_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{_sha256(path)[:10]}"
    snapshot = version_dir / f"{version_id}{path.suffix.lower()}"
    shutil.copy2(path, snapshot)
    (version_dir / f"{version_id}.json").write_text(
        json.dumps(
            {
                "id": version_id,
                "collection": collection,
                "path": relative_path,
                "action": action,
                "actor": actor.get("email") or actor.get("name") or "admin",
                "created_at": datetime.now().astimezone().isoformat(),
                "size": snapshot.stat().st_size,
                "sha256": _sha256(snapshot),
                "snapshot": snapshot.name,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return version_id


def _audit(actor: dict[str, Any], action: str, **details: Any) -> None:
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "actor": actor.get("email") or actor.get("name") or "admin",
        "action": action,
        **details,
    }
    with AUDIT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        tmp = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def require_admin(request: Request) -> dict[str, Any]:
    if DEV_AUTH_BYPASS:
        return {"id": "local-admin", "name": "Lokale Vorschau", "email": "admin@local", "role": "admin"}
    forwarded: dict[str, str] = {}
    for header in ("authorization", "cookie", "user-agent"):
        value = request.headers.get(header)
        if value:
            forwarded[header] = value
    try:
        response = requests.get(
            f"{OPENWEBUI_URL}/api/v1/auths/",
            headers=forwarded,
            timeout=10,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="auth_service_unavailable") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="openwebui_login_required")
    try:
        user = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="invalid_auth_response") from exc
    if str(user.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="admin_role_required")
    return user


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _unlock_code_matches(code: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = UNLOCK_CODE_HASH.split(".", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        if iterations < 200_000 or iterations > 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", code.encode("utf-8"), _b64url_decode(salt_raw), iterations
        )
        return hmac.compare_digest(actual, _b64url_decode(digest_raw))
    except (TypeError, ValueError):
        return False


def _unlock_subject(admin: dict[str, Any]) -> str:
    return str(admin.get("id") or admin.get("email") or "admin")


def _issue_unlock_token(admin: dict[str, Any]) -> str:
    payload = {
        "sub": _unlock_subject(admin),
        "exp": int(time.time()) + UNLOCK_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(12),
    }
    encoded = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        UNLOCK_SESSION_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_b64url_encode(signature)}"


def _has_valid_unlock(request: Request, admin: dict[str, Any]) -> bool:
    if DEV_AUTH_BYPASS:
        return True
    if not UNLOCK_ENABLED:
        return False
    token = request.cookies.get(UNLOCK_COOKIE, "")
    try:
        encoded, signature_raw = token.split(".", 1)
        expected = hmac.new(
            UNLOCK_SESSION_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, _b64url_decode(signature_raw)):
            return False
        payload = json.loads(_b64url_decode(encoded))
        return (
            isinstance(payload, dict)
            and str(payload.get("sub") or "") == _unlock_subject(admin)
            and int(payload.get("exp") or 0) > int(time.time())
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def _failure_key(request: Request, admin: dict[str, Any]) -> str:
    remote = request.client.host if request.client else "unknown"
    return f"{_unlock_subject(admin)}|{remote}"


def _attempt_state(request: Request, admin: dict[str, Any]) -> tuple[str, list[float]]:
    key = _failure_key(request, admin)
    cutoff = time.time() - UNLOCK_BLOCK_SECONDS
    with _unlock_failures_lock:
        recent = [stamp for stamp in _unlock_failures.get(key, []) if stamp >= cutoff]
        if recent:
            _unlock_failures[key] = recent
        else:
            _unlock_failures.pop(key, None)
    return key, recent


def require_unlocked_admin(
    request: Request, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    if not DEV_AUTH_BYPASS and not UNLOCK_ENABLED:
        raise HTTPException(status_code=503, detail="admin_unlock_not_configured")
    if not _has_valid_unlock(request, admin):
        raise HTTPException(status_code=423, detail="admin_unlock_required")
    return admin


def _qdrant(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = requests.request(method, f"{QDRANT_URL}{path}", timeout=45, **kwargs)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="qdrant_unavailable") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"qdrant_error_{response.status_code}")
    return response.json() if response.text else {}


def _trigger_reindex(collection: str, relative_path: str = "") -> dict[str, Any]:
    try:
        response = requests.post(
            f"{KB_SYNC_URL}/reindex",
            json={"collection": collection, "path": relative_path},
            timeout=180,
        )
        if response.status_code >= 400:
            return {"ok": False, "error": f"kb_sync_http_{response.status_code}"}
        payload = response.json()
        return payload if isinstance(payload, dict) else {"ok": True}
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def _document_summary(path: Path, collection: str, state: dict[str, Any]) -> dict[str, Any]:
    relative_path = path.relative_to(KB_ROOT / collection).as_posix()
    meta = _metadata(path)
    entry = _state_entry(state, collection, relative_path)
    return {
        "collection": collection,
        "path": relative_path,
        "name": path.name,
        "extension": path.suffix.lower().lstrip("."),
        "size": path.stat().st_size,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(),
        "chunks": int(entry.get("chunks") or 0),
        "indexed_at": entry.get("updated_at") or "",
        "index_status": _index_status(path, entry, bool(meta["rag_index"])),
        **meta,
    }


def _safe_archive_id(raw: str) -> str:
    archive_id = str(raw or "").strip()
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-z0-9][a-z0-9_-]+", archive_id):
        raise HTTPException(status_code=400, detail="invalid_archive_id")
    return archive_id


def _trash_manifest(archive: Path) -> dict[str, Any]:
    manifest_path = archive / ".trash.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            manifest = {}
    except Exception:
        manifest = {}
    match = re.fullmatch(r"(?P<stamp>[0-9]{8}-[0-9]{6})-(?P<collection>[a-z0-9][a-z0-9_-]+)", archive.name)
    if not match:
        raise ValueError("invalid_archive_name")
    archived_at = datetime.strptime(match.group("stamp"), "%Y%m%d-%H%M%S").astimezone()
    purge_at = archived_at + timedelta(days=TRASH_RETENTION_DAYS)
    collection = str(manifest.get("collection") or match.group("collection"))
    files = sum(
        1
        for path in archive.rglob("*")
        if path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return {
        "archive_id": archive.name,
        "collection": collection,
        "label": str(manifest.get("label") or _collection_label_from_root(archive, collection)),
        "files": int(manifest.get("files") or files),
        "archived_at": str(manifest.get("archived_at") or archived_at.isoformat()),
        "purge_at": str(manifest.get("purge_at") or purge_at.isoformat()),
        "retention_days": TRASH_RETENTION_DAYS,
    }


def _collection_label_from_root(root: Path, fallback: str) -> str:
    try:
        payload = json.loads((root / ".collection.json").read_text(encoding="utf-8"))
        label = str(payload.get("label") or "").strip()
        if label:
            return label
    except Exception:
        pass
    return COLLECTION_LABELS.get(fallback, fallback)


def _trash_collections() -> list[dict[str, Any]]:
    root = TRASH_ROOT / "collections"
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for archive in root.iterdir():
        if not archive.is_dir():
            continue
        try:
            items.append(_trash_manifest(archive))
        except ValueError:
            continue
    return sorted(items, key=lambda item: item["archived_at"], reverse=True)


def require_maintenance(request: Request) -> dict[str, Any]:
    authorization = request.headers.get("authorization", "")
    provided = authorization.removeprefix("Bearer ").strip()
    if not MAINTENANCE_API_KEY or not hmac.compare_digest(provided, MAINTENANCE_API_KEY):
        raise HTTPException(status_code=401, detail="maintenance_auth_required")
    return {"id": "system:trash-cleanup", "name": "Tägliche Papierkorb-Bereinigung"}


def _purge_expired_collections(*, dry_run: bool, actor: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now().astimezone()
    expired = [
        item
        for item in _trash_collections()
        if datetime.fromisoformat(item["purge_at"]) <= now
    ]
    purged: list[str] = []
    if not dry_run:
        for item in expired:
            archive = TRASH_ROOT / "collections" / item["archive_id"]
            if archive.exists():
                shutil.rmtree(archive)
                purged.append(item["archive_id"])
                _audit(actor, "collection_purged", **item)
    return {
        "ok": True,
        "dry_run": dry_run,
        "retention_days": TRASH_RETENTION_DAYS,
        "eligible": [item["archive_id"] for item in expired],
        "purged": purged,
    }

@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "version": APP_VERSION,
        "kb_root": str(KB_ROOT),
        "collections": list(_collection_names()),
    }


@app.get("/session")
def session(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    return {
        "id": admin.get("id"),
        "name": admin.get("name"),
        "email": admin.get("email"),
        "role": admin.get("role"),
    }


@app.get("/unlock/status")
def unlock_status(
    request: Request, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    return {
        "enabled": bool(UNLOCK_ENABLED or DEV_AUTH_BYPASS),
        "unlocked": _has_valid_unlock(request, admin),
        "ttl_seconds": UNLOCK_TTL_SECONDS,
    }


@app.post("/unlock")
def unlock(
    payload: UnlockRequest,
    request: Request,
    response: Response,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    if DEV_AUTH_BYPASS:
        return {"ok": True, "unlocked": True, "ttl_seconds": UNLOCK_TTL_SECONDS}
    if not UNLOCK_ENABLED:
        raise HTTPException(status_code=503, detail="admin_unlock_not_configured")
    key, recent = _attempt_state(request, admin)
    if len(recent) >= UNLOCK_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="admin_unlock_temporarily_blocked",
            headers={"Retry-After": str(UNLOCK_BLOCK_SECONDS)},
        )
    if not _unlock_code_matches(payload.code):
        with _unlock_failures_lock:
            _unlock_failures.setdefault(key, []).append(time.time())
        _audit(admin, "admin_unlock_failed", remote=request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail="admin_unlock_code_invalid")
    with _unlock_failures_lock:
        _unlock_failures.pop(key, None)
    response.set_cookie(
        key=UNLOCK_COOKIE,
        value=_issue_unlock_token(admin),
        max_age=UNLOCK_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/admin/vector",
    )
    _audit(admin, "admin_unlocked", ttl_seconds=UNLOCK_TTL_SECONDS)
    return {"ok": True, "unlocked": True, "ttl_seconds": UNLOCK_TTL_SECONDS}


@app.post("/lock")
def lock(
    response: Response, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    response.delete_cookie(
        key=UNLOCK_COOKIE,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/admin/vector",
    )
    _audit(admin, "admin_locked")
    return {"ok": True, "unlocked": False}

@app.get("/collections")
def list_collections(admin: dict[str, Any] = Depends(require_unlocked_admin)) -> dict[str, Any]:
    del admin
    state = _load_state()
    items: list[dict[str, Any]] = []
    for collection in _collection_names():
        root = KB_ROOT / collection
        documents = [
            path
            for path in root.rglob("*")
            if path.is_file()
            and not path.name.startswith((".", "~$"))
            and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ] if root.exists() else []
        collection_state = ((state.get("collections") or {}).get(collection) or {})
        items.append(
            {
                "id": collection,
                "label": _collection_label(collection),
                "files": len(documents),
                "last_indexed_at": collection_state.get("last_reconcile_at") or "",
                "deletable": collection not in COLLECTIONS,
            }
        )
    return {"collections": items}


@app.post("/collections", status_code=201)
def create_collection(
    payload: CreateCollectionRequest,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    collection = payload.id.strip().lower()
    if collection in _collection_names():
        raise HTTPException(status_code=409, detail="collection_already_exists")
    root = (KB_ROOT / collection).resolve()
    try:
        root.relative_to(KB_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_collection_path") from exc
    root.mkdir(parents=False, exist_ok=False)
    metadata = {
        "id": collection,
        "label": payload.label.strip(),
        "created_at": datetime.now().astimezone().isoformat(),
        "created_by": admin.get("email") or admin.get("name") or admin.get("id"),
    }
    _atomic_write(
        root / ".collection.json",
        json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    try:
        _qdrant(
            "PUT",
            f"/collections/{collection}",
            json={"vectors": {"size": 1024, "distance": "Cosine"}},
        )
    except HTTPException:
        shutil.rmtree(root)
        raise
    _audit(admin, "collection_created", collection=collection, label=payload.label.strip())
    return {"ok": True, "collection": {"id": collection, "label": payload.label.strip(), "files": 0, "deletable": True}}


@app.patch("/collections/{collection}")
def update_collection(
    collection: str,
    payload: UpdateCollectionRequest,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    collection = _safe_collection(collection)
    root = KB_ROOT / collection
    if not root.exists():
        raise HTTPException(status_code=404, detail="collection_source_missing")
    metadata_path = root / ".collection.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            metadata = {}
    except Exception:
        metadata = {}
    previous_label = _collection_label(collection)
    metadata.update(
        {
            "id": collection,
            "label": payload.label.strip(),
            "updated_at": datetime.now().astimezone().isoformat(),
            "updated_by": admin.get("email") or admin.get("name") or admin.get("id"),
        }
    )
    _atomic_write(
        metadata_path,
        json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    _audit(
        admin,
        "collection_updated",
        collection=collection,
        previous_label=previous_label,
        label=payload.label.strip(),
    )
    return {
        "ok": True,
        "collection": {
            "id": collection,
            "label": payload.label.strip(),
            "deletable": collection not in COLLECTIONS,
        },
    }


@app.delete("/collections/{collection}")
def delete_collection(
    collection: str,
    payload: DeleteCollectionRequest,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    collection = _safe_collection(collection)
    if collection in COLLECTIONS:
        raise HTTPException(status_code=409, detail="protected_collection")
    if payload.confirm_id.strip() != collection:
        raise HTTPException(status_code=400, detail="collection_confirmation_mismatch")
    root = KB_ROOT / collection
    if not root.exists():
        raise HTTPException(status_code=404, detail="collection_source_missing")
    archived_at = datetime.now().astimezone()
    purge_at = archived_at + timedelta(days=TRASH_RETENTION_DAYS)
    archive = TRASH_ROOT / "collections" / f"{archived_at.strftime('%Y%m%d-%H%M%S')}-{collection}"
    archive.parent.mkdir(parents=True, exist_ok=True)
    label = _collection_label(collection)
    files = sum(
        1
        for path in root.rglob("*")
        if path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    shutil.move(str(root), str(archive))
    try:
        _qdrant("DELETE", f"/collections/{collection}")
    except HTTPException:
        shutil.move(str(archive), str(root))
        raise
    manifest = {
        "collection": collection,
        "label": label,
        "files": files,
        "archived_at": archived_at.isoformat(),
        "purge_at": purge_at.isoformat(),
        "retention_days": TRASH_RETENTION_DAYS,
        "deleted_by": admin.get("email") or admin.get("name") or admin.get("id"),
    }
    _atomic_write(
        archive / ".trash.json",
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    _audit(
        admin,
        "collection_deleted",
        collection=collection,
        archived_path=archive.relative_to(KB_ROOT).as_posix(),
        purge_at=purge_at.isoformat(),
    )
    return {
        "ok": True,
        "collection": collection,
        "archived_path": archive.relative_to(KB_ROOT).as_posix(),
        "purge_at": purge_at.isoformat(),
        "retention_days": TRASH_RETENTION_DAYS,
    }


@app.get("/trash/collections")
def list_trashed_collections(
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    del admin
    return {
        "collections": _trash_collections(),
        "retention_days": TRASH_RETENTION_DAYS,
    }


@app.post("/trash/collections/{archive_id}/restore")
def restore_trashed_collection(
    archive_id: str,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    archive_id = _safe_archive_id(archive_id)
    archive = TRASH_ROOT / "collections" / archive_id
    if not archive.is_dir():
        raise HTTPException(status_code=404, detail="trash_collection_not_found")
    item = _trash_manifest(archive)
    collection = item["collection"]
    if collection in _collection_names():
        raise HTTPException(status_code=409, detail="collection_already_exists")
    destination = KB_ROOT / collection
    _qdrant(
        "PUT",
        f"/collections/{collection}",
        json={"vectors": {"size": 1024, "distance": "Cosine"}},
    )
    try:
        (archive / ".trash.json").unlink(missing_ok=True)
        shutil.move(str(archive), str(destination))
    except Exception:
        try:
            _qdrant("DELETE", f"/collections/{collection}")
        except HTTPException:
            pass
        raise
    reindex = _trigger_reindex(collection)
    _audit(admin, "collection_restored", archive_id=archive_id, collection=collection)
    return {
        "ok": True,
        "collection": {"id": collection, "label": item["label"], "files": item["files"]},
        "reindex": reindex,
    }


@app.delete("/trash/collections/{archive_id}")
def purge_trashed_collection(
    archive_id: str,
    payload: PurgeCollectionRequest,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    archive_id = _safe_archive_id(archive_id)
    archive = TRASH_ROOT / "collections" / archive_id
    if not archive.is_dir():
        raise HTTPException(status_code=404, detail="trash_collection_not_found")
    item = _trash_manifest(archive)
    if payload.confirm_id.strip() != item["collection"]:
        raise HTTPException(status_code=400, detail="collection_confirmation_mismatch")
    shutil.rmtree(archive)
    _audit(admin, "collection_purged", **item)
    return {"ok": True, "archive_id": archive_id, "collection": item["collection"]}


@app.post("/maintenance/trash-cleanup", include_in_schema=False)
def maintenance_trash_cleanup(
    request: Request,
    dry_run: bool = False,
) -> dict[str, Any]:
    actor = require_maintenance(request)
    return _purge_expired_collections(dry_run=dry_run, actor=actor)

@app.get("/collections/{collection}/documents")
def list_documents(
    collection: str,
    query: str = "",
    extension: str = "",
    expiry: str = "",
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    del admin
    collection = _safe_collection(collection)
    state = _load_state()
    root = KB_ROOT / collection
    documents: list[dict[str, Any]] = []
    if root.exists():
        for path in root.rglob("*"):
            if (
                not path.is_file()
                or path.name.startswith((".", "~$"))
                or path.suffix.lower() not in SUPPORTED_EXTENSIONS
            ):
                continue
            item = _document_summary(path, collection, state)
            haystack = " ".join(
                [
                    item["name"],
                    item["path"],
                    item["title"],
                    item["owner"],
                    " ".join(item["tags"] if isinstance(item["tags"], list) else []),
                ]
            ).lower()
            if query and query.lower() not in haystack:
                continue
            if extension and item["extension"] != extension.lower().lstrip("."):
                continue
            if expiry and item["expiry_status"] != expiry:
                continue
            documents.append(item)
    documents.sort(key=lambda item: item["modified_at"], reverse=True)
    return {"collection": collection, "documents": documents, "count": len(documents)}


@app.get("/collections/{collection}/documents/{relative_path:path}")
def get_document(
    collection: str,
    relative_path: str,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    del admin
    path = _document_path(collection, relative_path)
    state = _load_state()
    summary = _document_summary(path, collection, state)
    preview = _extract_preview(path)
    return {
        **summary,
        "editable": path.suffix.lower() in EDITABLE_EXTENSIONS,
        "content": preview if path.suffix.lower() in EDITABLE_EXTENSIONS else "",
        "preview": preview[:200_000],
    }


@app.put("/collections/{collection}/documents/{relative_path:path}")
def save_document(
    collection: str,
    relative_path: str,
    payload: SaveDocumentRequest,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    path = _document_path(collection, relative_path)
    if path.suffix.lower() not in EDITABLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="binary_document_replace_via_upload")
    version_id = _create_version(path, collection, relative_path, admin, "save")
    _atomic_write(path, payload.content.encode("utf-8"))
    _audit(admin, "document_saved", collection=collection, path=relative_path, version_id=version_id)
    reindex = _trigger_reindex(collection, relative_path)
    return {
        "ok": True,
        "version_id": version_id,
        "reindex": reindex,
        "document": _document_summary(path, collection, _load_state()),
    }


@app.post("/upload")
async def upload_document(
    collection: str = Form(...),
    target_path: str = Form(""),
    file: UploadFile = File(...),
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    collection = _safe_collection(collection)
    filename = Path(file.filename or "").name
    relative = target_path.strip() or filename
    destination = _document_path(collection, relative, must_exist=False)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="upload_too_large")
    version_id = ""
    if destination.exists():
        version_id = _create_version(destination, collection, relative, admin, "replace_upload")
    _atomic_write(destination, data)
    _audit(
        admin,
        "document_uploaded",
        collection=collection,
        path=relative,
        size=len(data),
        version_id=version_id,
    )
    reindex = _trigger_reindex(collection, relative)
    return {
        "ok": True,
        "version_id": version_id,
        "reindex": reindex,
        "document": _document_summary(destination, collection, _load_state()),
    }


@app.post("/collections/{collection}/documents/{relative_path:path}/move")
def move_document(
    collection: str,
    relative_path: str,
    payload: MoveDocumentRequest,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    source = _document_path(collection, relative_path)
    target_collection = _safe_collection(payload.target_collection)
    target = _document_path(target_collection, payload.target_path, must_exist=False)
    if target.exists():
        raise HTTPException(status_code=409, detail="target_already_exists")
    _create_version(source, collection, relative_path, admin, "move")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.replace(target)
    _audit(
        admin,
        "document_moved",
        collection=collection,
        path=relative_path,
        target_collection=target_collection,
        target_path=payload.target_path,
    )
    source_reindex = _trigger_reindex(collection, relative_path)
    target_reindex = _trigger_reindex(target_collection, payload.target_path)
    return {"ok": True, "collection": target_collection, "path": payload.target_path, "reindex": {"source": source_reindex, "target": target_reindex}}


@app.delete("/collections/{collection}/documents/{relative_path:path}")
def delete_document(
    collection: str,
    relative_path: str,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    source = _document_path(collection, relative_path)
    version_id = _create_version(source, collection, relative_path, admin, "delete")
    trash_path = (
        TRASH_ROOT
        / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        / collection
        / Path(*_safe_relative_path(relative_path).parts)
    )
    trash_path.parent.mkdir(parents=True, exist_ok=True)
    source.replace(trash_path)
    _audit(
        admin,
        "document_deleted",
        collection=collection,
        path=relative_path,
        trash_path=trash_path.relative_to(KB_ROOT).as_posix(),
        version_id=version_id,
    )
    reindex = _trigger_reindex(collection, relative_path)
    return {"ok": True, "recoverable": True, "version_id": version_id, "reindex": reindex}


@app.get("/collections/{collection}/chunks/{relative_path:path}")
def document_chunks(
    collection: str,
    relative_path: str,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    del admin
    _document_path(collection, relative_path)
    doc_id = f"{collection}/{_safe_relative_path(relative_path).as_posix()}"
    result = _qdrant(
        "POST",
        f"/collections/{collection}/points/scroll",
        json={
            "limit": 256,
            "with_payload": True,
            "with_vector": False,
            "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]},
        },
    ).get("result") or {}
    chunks = []
    for point in result.get("points") or []:
        payload = point.get("payload") or {}
        chunks.append(
            {
                "id": point.get("id"),
                "index": int(payload.get("chunk_index") or 0),
                "content": payload.get("content") or payload.get("text") or "",
            }
        )
    chunks.sort(key=lambda item: item["index"])
    return {"doc_id": doc_id, "chunks": chunks, "count": len(chunks)}


@app.get("/collections/{collection}/versions/{relative_path:path}")
def document_versions(
    collection: str,
    relative_path: str,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    del admin
    _safe_collection(collection)
    _safe_relative_path(relative_path)
    version_dir = _version_key(collection, relative_path)
    versions = []
    if version_dir.exists():
        for meta_path in version_dir.glob("*.json"):
            try:
                versions.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except Exception:
                continue
    versions.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {"versions": versions}


@app.post("/collections/{collection}/restore/{relative_path:path}")
def restore_version(
    collection: str,
    relative_path: str,
    payload: RestoreVersionRequest,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    destination = _document_path(collection, relative_path, must_exist=False)
    version_dir = _version_key(collection, relative_path)
    meta_path = version_dir / f"{payload.version_id}.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="version_not_found")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    snapshot = version_dir / str(meta.get("snapshot") or "")
    if not snapshot.exists():
        raise HTTPException(status_code=404, detail="version_snapshot_missing")
    if destination.exists():
        _create_version(destination, collection, relative_path, admin, "before_restore")
    _atomic_write(destination, snapshot.read_bytes())
    _audit(
        admin,
        "version_restored",
        collection=collection,
        path=relative_path,
        version_id=payload.version_id,
    )
    reindex = _trigger_reindex(collection, relative_path)
    return {"ok": True, "reindex": reindex, "document": _document_summary(destination, collection, _load_state())}


@app.get("/search")
def semantic_search(
    query: str,
    limit: int = 12,
    admin: dict[str, Any] = Depends(require_unlocked_admin),
) -> dict[str, Any]:
    del admin
    clean_query = " ".join(query.split())
    if len(clean_query) < 2:
        return {"query": clean_query, "results": []}
    limit = max(1, min(limit, 30))
    if not IONOS_API_KEY:
        raise HTTPException(status_code=503, detail="embedding_api_not_configured")
    try:
        embedding_response = requests.post(
            f"{IONOS_BASE_URL}/embeddings",
            headers={"Authorization": f"Bearer {IONOS_API_KEY}"},
            json={"model": EMBEDDING_MODEL, "input": [clean_query]},
            timeout=120,
        )
        embedding_response.raise_for_status()
        vector = embedding_response.json()["data"][0]["embedding"]
    except Exception as exc:
        raise HTTPException(status_code=503, detail="embedding_request_failed") from exc
    results: list[dict[str, Any]] = []
    per_collection = max(4, min(limit, 12))
    for collection in _collection_names():
        payload = _qdrant(
            "POST",
            f"/collections/{collection}/points/search",
            json={
                "vector": vector,
                "limit": per_collection,
                "with_payload": True,
                "with_vector": False,
            },
        )
        for point in (payload.get("result") or []):
            source = point.get("payload") or {}
            results.append(
                {
                    "collection": collection,
                    "path": source.get("source_path") or "",
                    "doc_id": source.get("doc_id") or "",
                    "chunk_index": int(source.get("chunk_index") or 0),
                    "content": source.get("content") or source.get("text") or "",
                    "score": float(point.get("score") or 0),
                }
            )
    results.sort(key=lambda item: item["score"], reverse=True)
    return {"query": clean_query, "results": results[:limit]}

