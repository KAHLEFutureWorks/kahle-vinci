import os
import glob
import time
import uuid
import re
import hmac
import hashlib
import base64
import binascii
import mimetypes
import json
import sqlite3
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.responses import Response, JSONResponse, FileResponse, RedirectResponse
from pydantic import BaseModel, Field, constr

OWUI_UPLOAD_DIR = os.getenv("OWUI_UPLOAD_DIR", "/app/backend/data/uploads")
DOC_WORKER_URL = os.getenv("DOC_WORKER_URL", "http://document-worker:8090")

# Backwards-compatible: TOOL_API_KEY protects proxy endpoints (optional),
# and is also forwarded to worker as x-api-key (optional).
TOOL_API_KEY = os.getenv("TOOL_API_KEY", "")
WORKER_API_KEY = os.getenv("WORKER_API_KEY", "") or TOOL_API_KEY

UPLOAD_ROOT = Path(OWUI_UPLOAD_DIR).resolve()

# Output subfolder for saved files
OUTPUT_SUBDIR = os.getenv("OWUI_OUTPUT_SUBDIR", "edited").strip("/")
OWUI_DB_PATH = Path(os.getenv("OWUI_DB_PATH", "/app/backend/data/webui.db"))
OWUI_LOG_CLEANUP_REPORT_PATH = Path(
    os.getenv("OWUI_LOG_CLEANUP_REPORT_PATH", "/retention-reports/openwebui_log_cleanup_report.json")
)
OWUI_LOG_CLEANUP_STALE_HOURS = int(os.getenv("OWUI_LOG_CLEANUP_STALE_HOURS", "36"))

# Size limit
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", "20000000"))  # 20 MB

# Signed download links
FILE_LINK_SECRET = os.getenv("FILE_LINK_SECRET", "")
FILE_LINK_TTL_SECONDS = int(os.getenv("FILE_LINK_TTL_SECONDS", "3600"))
ALLOW_UNSIGNED_DOWNLOADS = os.getenv("ALLOW_UNSIGNED_DOWNLOADS", "false").lower() == "true"

# Optional: absolute links in chat
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# Multi-user safety toggles
REQUIRE_EXACT_FILE_PATH = os.getenv("REQUIRE_EXACT_FILE_PATH", "false").lower() == "true"
DISALLOW_WILDCARDS = os.getenv("DISALLOW_WILDCARDS", "true").lower() == "true"

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MIME = "application/pdf"

# Allow saving these file types from worker results
ALLOWED_SAVE_EXT = {".docx", ".md", ".txt", ".csv", ".pdf", ".xlsx"}

WILDCARD_RE = re.compile(r"[*?\[\]{}]")
NonEmptyStr = constr(strip_whitespace=True, min_length=1)


app = FastAPI(title="OWUI File Proxy", version="1.5.0")


# -----------------------------
# Security helpers
# -----------------------------
def _require_api_key(x_api_key: Optional[str]) -> None:
    if TOOL_API_KEY:
        if x_api_key != TOOL_API_KEY:
            raise HTTPException(status_code=401, detail="unauthorized")


def _ensure_within_upload_root(resolved: Path) -> None:
    try:
        resolved.relative_to(UPLOAD_ROOT)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path: outside uploads directory.")


def _safe_relpath(rel: str) -> str:
    rel = (rel or "").replace("\\", "/").lstrip("/")
    parts = [p for p in rel.split("/") if p]
    if any(p == ".." for p in parts):
        raise HTTPException(status_code=400, detail="invalid_path")
    return "/".join(parts)


def _sanitize_filename(name: str) -> str:
    name = os.path.basename(name or "")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    if not name:
        name = f"file_{uuid.uuid4().hex}"
    return name


def _reject_wildcards(raw: str) -> None:
    if not raw:
        return
    if DISALLOW_WILDCARDS and WILDCARD_RE.search(raw):
        raise HTTPException(status_code=400, detail="wildcards_not_allowed_use_exact_filename")


# -----------------------------
# File selection
# -----------------------------
def _list_files(pattern: str) -> list[Path]:
    files = [Path(p) for p in glob.glob(str(UPLOAD_ROOT / pattern), recursive=True)]
    return [p for p in files if p.is_file()]


def _pick_latest_file_by_exts(allowed_exts: tuple[str, ...]) -> Path:
    # NOTE: In strict mode we generally don't want "latest". This exists for backwards compatibility.
    candidates: list[Path] = []
    for ext in allowed_exts:
        ext = ext.lstrip(".")
        candidates += _list_files(f"**/*.{ext}")

    if not candidates:
        raise HTTPException(
            status_code=400,
            detail=f"No matching files found in OWUI_UPLOAD_DIR={UPLOAD_ROOT} for extensions={allowed_exts}",
        )

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _resolve_path(
    file_path: str | None,
    allowed_exts: tuple[str, ...],
    require_exact: bool = False,
    preferred_exact_paths: Optional[list[str]] = None,
) -> Path:
    """
    Resolve file_path safely inside UPLOAD_ROOT.

    Accepts:
      - filename only (e.g. 'test.docx') -> search recursively in uploads
      - relative path under uploads -> resolve
      - absolute path, but must still be inside uploads

    Strict mode / exact mode:
      - file_path MUST be provided and non-null.
      - ambiguous bare filenames are rejected; user must provide the exact relative path.
    """
    strict = REQUIRE_EXACT_FILE_PATH or require_exact
    if strict and (file_path is None or str(file_path).strip() in ("", "null", "None")):
        raise HTTPException(status_code=400, detail="file_path_required_use_exact_uploaded_filename")

    if not file_path:
        return _pick_latest_file_by_exts(allowed_exts)

    raw = file_path.strip()
    if raw in ("null", "None", ""):
        return _pick_latest_file_by_exts(allowed_exts)

    # Normalize common client-side path hints.
    raw = raw.replace("\\", "/").lstrip("/")
    if raw.startswith("./"):
        raw = raw[2:]
    if raw.startswith("uploads/"):
        raw = raw[len("uploads/") :]

    # Reject obvious filename placeholders generated by model guesses.
    lowered = raw.lower()
    if any(tok in lowered for tok in ("dateiname", "datenname", "your_file", "your_", "anhang", "<", ">")):
        raise HTTPException(status_code=400, detail="placeholder_filename_not_allowed_use_exact_uploaded_filename")

    _reject_wildcards(raw)

    p = Path(raw)

    # filename only -> search
    if ("/" not in raw) and ("\\" not in raw):
        hits = _list_files(f"**/{raw}")
        if not hits:
            # OWUI often stores files as "<uuid>_<original_name>".
            hits = _list_files(f"**/*_{raw}")
        if not hits:
            raise HTTPException(status_code=400, detail=f"File not found in uploads: {raw}")

        # Optional deterministic disambiguation using exact paths from the current message attachments.
        if len(hits) > 1 and preferred_exact_paths:
            preferred_set = set()
            for p in preferred_exact_paths:
                if not isinstance(p, str):
                    continue
                cand = p.strip().replace("\\", "/").lstrip("/")
                if cand.startswith("uploads/"):
                    cand = cand[len("uploads/") :]
                if cand:
                    preferred_set.add(cand)
                    preferred_set.add(cand.split("/")[-1])

            filtered = []
            for h in hits:
                try:
                    rel = str(h.resolve().relative_to(UPLOAD_ROOT)).replace("\\", "/")
                except Exception:
                    rel = h.name
                if rel in preferred_set or h.name in preferred_set:
                    filtered.append(h)

            if len(filtered) == 1:
                hits = filtered

        if strict and len(hits) > 1:
            matches = []
            for h in hits[:20]:
                try:
                    rel = str(h.resolve().relative_to(UPLOAD_ROOT)).replace("\\", "/")
                except Exception:
                    rel = h.name
                matches.append(rel)
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "ambiguous_filename_use_exact_relative_path",
                    "filename": raw,
                    "matches": matches,
                },
            )
        hits.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        resolved = hits[0].resolve()
    else:
        # treat as path
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (UPLOAD_ROOT / p).resolve()

    _ensure_within_upload_root(resolved)

    allowed_lower = [e.lower() for e in allowed_exts]
    if resolved.suffix.lower() not in allowed_lower:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {resolved.suffix}. Allowed: {', '.join(allowed_exts)}",
        )

    if not resolved.is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {resolved}")

    return resolved


def _read_file(path: Path) -> bytes:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"file_too_large (>{MAX_FILE_BYTES} bytes)")
    with open(path, "rb") as f:
        return f.read()


# -----------------------------
# Worker headers (forwarding)
# -----------------------------
def _worker_headers() -> dict:
    h = {}
    if WORKER_API_KEY:
        h["x-api-key"] = WORKER_API_KEY
    return h


def _raise_for_worker_response(r: requests.Response) -> None:
    """
    Preserve upstream worker error semantics for tool callers.
    - 4xx from worker should stay 4xx (validation/user-fixable)
    - 5xx from worker is mapped to 502
    """
    if r.status_code == 200:
        return

    detail: Any
    try:
        payload = r.json()
        detail = payload.get("detail", payload)
    except Exception:
        detail = (r.text or "").strip()[:2000] or f"worker_http_error_{r.status_code}"

    status = r.status_code if 400 <= r.status_code < 500 else 502
    raise HTTPException(status_code=status, detail=detail)


# -----------------------------
# Signing + saving
# -----------------------------
def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _b64decode_strict(b64: str) -> bytes:
    try:
        data = base64.b64decode(b64, validate=True)
    except binascii.Error:
        raise HTTPException(status_code=400, detail="invalid_base64")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"file_too_large (>{MAX_FILE_BYTES} bytes)")
    return data


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _sign_download(rel: str, exp: int) -> str:
    if not FILE_LINK_SECRET:
        raise HTTPException(status_code=500, detail="FILE_LINK_SECRET not set")
    msg = f"{exp}:{rel}".encode("utf-8")
    return hmac.new(FILE_LINK_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _verify_sig(rel: str, exp: int, sig: str) -> None:
    if exp < int(time.time()):
        raise HTTPException(status_code=410, detail="link_expired")
    if ALLOW_UNSIGNED_DOWNLOADS:
        return
    expected = _sign_download(rel, exp)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="bad_signature")


def _build_download_url(rel: str) -> str:
    exp = int(time.time()) + FILE_LINK_TTL_SECONDS
    sig = "unsigned" if ALLOW_UNSIGNED_DOWNLOADS else _sign_download(rel, exp)
    path = f"/files/download?rel={rel}&exp={exp}&sig={sig}"
    return f"{PUBLIC_BASE_URL}{path}" if PUBLIC_BASE_URL else path


def _save_bytes(filename: str, data: bytes) -> dict:
    safe_name = _sanitize_filename(filename)
    ext = Path(safe_name).suffix.lower()
    if ext and ext not in ALLOWED_SAVE_EXT:
        raise HTTPException(status_code=400, detail=f"extension_not_allowed: {ext}")

    ts = time.strftime("%Y%m%d_%H%M%S")
    rand = uuid.uuid4().hex[:8]
    rel = _safe_relpath(f"{OUTPUT_SUBDIR}/{ts}_{rand}_{safe_name}")

    abs_path = (UPLOAD_ROOT / rel).resolve()
    _ensure_within_upload_root(abs_path)

    _write_atomic(abs_path, data)

    return {
        "output_kind": "file_saved",
        "saved_rel_path": rel,
        "filename": safe_name,
        "size_bytes": len(data),
        "sha256": _sha256(data),
        "download_url": _build_download_url(rel),
    }


# -----------------------------
# Request models
# -----------------------------
class SaveB64Request(BaseModel):
    filename: str = Field(..., description="Output filename, e.g. edited.docx")
    content_type: str = Field(..., description="MIME type")
    content_base64: str = Field(..., description="Base64 content (no data: prefix)")


class ReplaceOneSaveRequest(BaseModel):
    from_text: str = Field(..., description="Text to find (first occurrence)")
    to_text: str = Field(..., description="Replacement text")
    file_path: NonEmptyStr = Field(..., description="Exact filename/path in uploads")


class BundleToMdRequest(BaseModel):
    title: str = Field("Masterkontext", description="Title for the bundle output")
    file_paths: Optional[list[str]] = Field(None, description="List of exact filenames/paths in uploads")

class BundleToMdSaveRequest(BaseModel):
    title: str = Field("Masterkontext", description="Title for the bundle output")
    file_paths: list[NonEmptyStr] = Field(..., min_length=1, description="List of exact filenames/paths in uploads")


class DocxDeleteLastParagraphsSaveRequest(BaseModel):
    file_path: NonEmptyStr = Field(..., description="Exact DOCX filename in uploads")
    n: int = Field(3, ge=1, le=500, description="How many paragraphs to delete from the end")
    allow_empty_output: bool = Field(
        False,
        description="If false, block operations that would remove all non-empty DOCX paragraphs.",
    )


class TextApplyOpsSaveRequest(BaseModel):
    file_path: NonEmptyStr = Field(..., description="Exact TXT/MD/CSV filename in uploads")
    ops: list[dict[str, Any]] = Field(..., description="List of deterministic text ops")
    allow_empty_output: bool = Field(
        False,
        description="If false, block operations that would result in a 0-byte file.",
    )


class PdfRemovePagesSaveRequest(BaseModel):
    file_path: NonEmptyStr = Field(..., description="Exact PDF filename in uploads")
    remove_pages: list[int] = Field(..., description="1-based page numbers to remove, e.g. [1,2]")


class PdfMergeSaveRequest(BaseModel):
    file_paths: list[NonEmptyStr] = Field(..., min_length=2, description="At least 2 exact PDF filenames in uploads")
    output_name: str = Field("merged.pdf", description="Output filename")
    attachment_exact_paths: Optional[list[str]] = Field(
        default=None,
        description="Internal: exact attachment paths from current OWUI message for disambiguation.",
    )


class XlsxUpdateCellsSaveRequest(BaseModel):
    file_path: NonEmptyStr = Field(..., description="Exact XLSX filename in uploads")
    updates: list[dict[str, Any]] = Field(
        ...,
        description='Cell/range updates, e.g. [{"sheet":"Sheet1","cell":"B2","value":"123"}] or [{"range":"A2:A500","generator":"random_money","min":1000,"max":100000}]',
    )


class DocxToPdfSaveRequest(BaseModel):
    file_path: NonEmptyStr = Field(..., description="Exact DOCX filename in uploads")
    output_name: str = Field("converted.pdf", description="Output PDF filename")


class FileToMdSaveRequest(BaseModel):
    file_path: NonEmptyStr = Field(..., description="Exact filename in uploads (docx/pdf/md/txt/xlsx/csv)")
    title: str = Field("Konvertiert", description="Heading title for markdown conversion")
    output_name: Optional[NonEmptyStr] = Field(None, description="Optional output filename, defaults to source stem + .md")


class CleanupOldFilesRequest(BaseModel):
    days: int = Field(15, ge=1, le=3650, description="Delete files older than this many days")
    dry_run: bool = Field(False, description="If true, list files only, do not delete")
    include_uploads: bool = Field(True, description="Include /uploads root")
    include_edited: bool = Field(True, description="Include /edited output folder")
    include_legacy_edited: bool = Field(
        True,
        description="Also include legacy /app/backend/data/edited when uploads root is /app/backend/data/uploads",
    )
    max_files: int = Field(100000, ge=1, le=1000000, description="Safety limit for processed files")


class CleanupOpenWebUIChatsRequest(BaseModel):
    days: int = Field(60, ge=1, le=3650, description="Delete chats older than this many days")
    dry_run: bool = Field(False, description="If true, only return candidates")
    keep_pinned: bool = Field(True, description="If true, never delete pinned chats")
    max_delete: int = Field(5000, ge=1, le=100000, description="Safety limit for deleted chats per run")
    vacuum: bool = Field(True, description="If true, run VACUUM after deletion")


# -----------------------------
# Endpoints
# -----------------------------
@app.get("/health", include_in_schema=False)
def health():
    return {
        "ok": True,
        "owui_upload_dir": str(UPLOAD_ROOT),
        "doc_worker_url": DOC_WORKER_URL,
        "output_subdir": OUTPUT_SUBDIR,
        "max_file_bytes": MAX_FILE_BYTES,
        "signed_downloads_enabled": bool(FILE_LINK_SECRET) and not ALLOW_UNSIGNED_DOWNLOADS,
        "allow_unsigned_downloads": ALLOW_UNSIGNED_DOWNLOADS,
        "public_base_url": PUBLIC_BASE_URL or None,
        "require_exact_file_path": REQUIRE_EXACT_FILE_PATH,
        "disallow_wildcards": DISALLOW_WILDCARDS,
    }


def _cleanup_dir_old_files(target: Path, cutoff_ts: float, dry_run: bool, max_files: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(target),
        "exists": target.exists() and target.is_dir(),
        "checked_files": 0,
        "matched_files": 0,
        "deleted_files": 0,
        "deleted_bytes": 0,
        "samples": [],
        "truncated": False,
    }
    if not result["exists"]:
        return result

    processed = 0
    for p in target.rglob("*"):
        if not p.is_file():
            continue
        processed += 1
        if processed > max_files:
            result["truncated"] = True
            break
        result["checked_files"] += 1
        try:
            st = p.stat()
        except Exception:
            continue
        if float(st.st_mtime) >= cutoff_ts:
            continue

        result["matched_files"] += 1
        try:
            rel = str(p.resolve().relative_to(UPLOAD_ROOT)).replace("\\", "/")
        except Exception:
            rel = str(p.name)
        if len(result["samples"]) < 200:
            result["samples"].append(rel)

        if dry_run:
            continue
        try:
            size = int(st.st_size)
            p.unlink(missing_ok=True)
            result["deleted_files"] += 1
            result["deleted_bytes"] += size
        except Exception:
            continue

    if not dry_run:
        # Clean empty subdirectories but keep the directory itself.
        for d in sorted([x for x in target.rglob("*") if x.is_dir()], key=lambda x: len(x.parts), reverse=True):
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except Exception:
                continue

    return result


def _parse_iso_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_log_cleanup_report() -> dict[str, Any]:
    if not OWUI_LOG_CLEANUP_REPORT_PATH.exists() or not OWUI_LOG_CLEANUP_REPORT_PATH.is_file():
        return {
            "ok": True,
            "exists": False,
            "report_path": str(OWUI_LOG_CLEANUP_REPORT_PATH),
            "success": False,
            "stale": True,
            "reason": "report_not_found",
        }
    try:
        payload = json.loads(OWUI_LOG_CLEANUP_REPORT_PATH.read_text(encoding="utf-8-sig"))
    except Exception as e:
        return {
            "ok": True,
            "exists": True,
            "report_path": str(OWUI_LOG_CLEANUP_REPORT_PATH),
            "success": False,
            "stale": True,
            "reason": "invalid_report_json",
            "error": str(e),
        }

    last_run = payload.get("last_run_at")
    run_dt = _parse_iso_ts(last_run)
    now_dt = datetime.now(timezone.utc)
    stale = True
    age_hours: Optional[float] = None
    if run_dt:
        age_hours = max(0.0, (now_dt - run_dt).total_seconds() / 3600.0)
        stale = age_hours > float(OWUI_LOG_CLEANUP_STALE_HOURS)

    return {
        "ok": True,
        "exists": True,
        "report_path": str(OWUI_LOG_CLEANUP_REPORT_PATH),
        "last_run_at": last_run,
        "success": bool(payload.get("success", False)),
        "cutoff_days": int(payload.get("cutoff_days", 0) or 0),
        "lines_before": int(payload.get("lines_before", 0) or 0),
        "lines_after": int(payload.get("lines_after", 0) or 0),
        "lines_deleted": int(payload.get("lines_deleted", 0) or 0),
        "open_webui_restarted": bool(payload.get("open_webui_restarted", False)),
        "stale": stale,
        "age_hours": age_hours,
        "error": payload.get("error"),
    }


@app.post("/maintenance/cleanup_old_files", include_in_schema=False)
def maintenance_cleanup_old_files(
    payload: CleanupOldFilesRequest,
    x_api_key: Optional[str] = Header(default=None),
):
    _require_api_key(x_api_key)

    now_ts = time.time()
    cutoff_ts = now_ts - (payload.days * 86400)

    targets: list[Path] = []
    if payload.include_uploads:
        targets.append(UPLOAD_ROOT)
    # /edited lives under /uploads, so avoid double-processing when uploads is selected.
    if payload.include_edited and not payload.include_uploads:
        edited_dir = (UPLOAD_ROOT / OUTPUT_SUBDIR).resolve()
        _ensure_within_upload_root(edited_dir)
        if edited_dir not in targets:
            targets.append(edited_dir)
    if payload.include_legacy_edited:
        base_parent = UPLOAD_ROOT.parent.resolve()
        legacy_edited_dir = (base_parent / OUTPUT_SUBDIR).resolve()
        try:
            legacy_edited_dir.relative_to(base_parent)
        except Exception:
            legacy_edited_dir = None
        if (
            legacy_edited_dir
            and legacy_edited_dir != UPLOAD_ROOT
            and legacy_edited_dir not in targets
        ):
            targets.append(legacy_edited_dir)

    reports = []
    for t in targets:
        reports.append(
            _cleanup_dir_old_files(
                target=t,
                cutoff_ts=cutoff_ts,
                dry_run=payload.dry_run,
                max_files=payload.max_files,
            )
        )

    summary = {
        "ok": True,
        "dry_run": payload.dry_run,
        "days": payload.days,
        "cutoff_unix": int(cutoff_ts),
        "targets_count": len(reports),
        "checked_files": sum(int(r.get("checked_files", 0)) for r in reports),
        "matched_files": sum(int(r.get("matched_files", 0)) for r in reports),
        "deleted_files": sum(int(r.get("deleted_files", 0)) for r in reports),
        "deleted_bytes": sum(int(r.get("deleted_bytes", 0)) for r in reports),
        "reports": reports,
    }
    return summary


@app.post("/maintenance/cleanup_openwebui_chats", include_in_schema=False)
def maintenance_cleanup_openwebui_chats(
    payload: CleanupOpenWebUIChatsRequest,
    x_api_key: Optional[str] = Header(default=None),
):
    _require_api_key(x_api_key)
    cutoff_ts = int(time.time() - (payload.days * 86400))

    if not OWUI_DB_PATH.exists() or not OWUI_DB_PATH.is_file():
        raise HTTPException(status_code=500, detail=f"openwebui_db_not_found: {OWUI_DB_PATH}")

    conn = sqlite3.connect(str(OWUI_DB_PATH), timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row

        where_sql = "CAST(updated_at AS INTEGER) < ?"
        where_args: list[Any] = [cutoff_ts]
        if payload.keep_pinned:
            where_sql += " AND COALESCE(pinned, 0) = 0"

        candidates = int(conn.execute(f"SELECT COUNT(*) AS c FROM chat WHERE {where_sql}", where_args).fetchone()["c"])
        skipped_pinned = 0
        if payload.keep_pinned:
            skipped_pinned = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM chat WHERE CAST(updated_at AS INTEGER) < ? AND COALESCE(pinned, 0) != 0",
                    (cutoff_ts,),
                ).fetchone()["c"]
            )

        rows = conn.execute(
            f"SELECT id FROM chat WHERE {where_sql} ORDER BY CAST(updated_at AS INTEGER) ASC LIMIT ?",
            [*where_args, payload.max_delete],
        ).fetchall()
        candidate_ids = [str(r["id"]) for r in rows if r["id"]]

        deleted_tags = 0
        deleted_chats = 0
        vacuum_ran = False

        if candidate_ids and not payload.dry_run:
            placeholders = ",".join("?" for _ in candidate_ids)
            conn.execute("BEGIN")
            try:
                deleted_tags = int(
                    conn.execute(
                        f"DELETE FROM chatidtag WHERE chat_id IN ({placeholders})",
                        candidate_ids,
                    ).rowcount
                    or 0
                )
                deleted_chats = int(
                    conn.execute(
                        f"DELETE FROM chat WHERE id IN ({placeholders})",
                        candidate_ids,
                    ).rowcount
                    or 0
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

            if payload.vacuum and deleted_chats > 0:
                conn.execute("VACUUM")
                vacuum_ran = True

        return {
            "ok": True,
            "dry_run": payload.dry_run,
            "days": payload.days,
            "keep_pinned": payload.keep_pinned,
            "max_delete": payload.max_delete,
            "cutoff_unix": cutoff_ts,
            "candidates": candidates,
            "selected_for_delete": len(candidate_ids),
            "deleted_chats": deleted_chats,
            "deleted_tags": deleted_tags,
            "skipped_pinned": skipped_pinned,
            "sample_chat_ids": candidate_ids[:20],
            "vacuum_ran": vacuum_ran,
        }
    finally:
        conn.close()


@app.get("/maintenance/openwebui_log_cleanup_status", include_in_schema=False)
def maintenance_openwebui_log_cleanup_status(x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)
    return _load_log_cleanup_report()


@app.post("/files/save_b64", include_in_schema=False)
def files_save_b64(payload: SaveB64Request, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)
    data = _b64decode_strict(payload.content_base64)
    saved = _save_bytes(payload.filename, data)
    saved["content_type"] = payload.content_type
    return saved


@app.get("/files/download", include_in_schema=False)
def files_download(
    rel: str = Query(..., description="Relative path under uploads"),
    exp: Optional[int] = Query(default=None, description="Expiry (unix timestamp)"),
    sig: Optional[str] = Query(default=None, description="HMAC signature"),
):
    rel = _safe_relpath(rel)

    if not ALLOW_UNSIGNED_DOWNLOADS:
        # Compatibility fallback:
        # Some LLM replies may accidentally output a truncated link that only keeps `rel`.
        # If signature params are missing, issue a short-lived signed redirect.
        if exp is None or not sig:
            signed_url = _build_download_url(rel)
            return RedirectResponse(url=signed_url, status_code=307)

        _verify_sig(rel, exp, sig)

    abs_path = (UPLOAD_ROOT / rel).resolve()
    _ensure_within_upload_root(abs_path)

    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(status_code=404, detail="file_not_found")

    media_type, _ = mimetypes.guess_type(abs_path.name)
    media_type = media_type or "application/octet-stream"

    return FileResponse(path=str(abs_path), filename=abs_path.name, media_type=media_type)


# -----------------------------
# DOCX: replace_one (existing)
# -----------------------------
@app.post("/docx/replace_one_b64", include_in_schema=False)
def docx_replace_one_b64(
    from_text: str,
    to_text: str,
    file_path: str | None = None,
    x_api_key: Optional[str] = Header(default=None),
):
    _require_api_key(x_api_key)

    path = _resolve_path(file_path, allowed_exts=(".docx",))
    data = _read_file(path)

    files = {"file": (path.name, data, DOCX_MIME)}
    form = {"from_text": from_text, "to_text": to_text}

    r = requests.post(
        f"{DOC_WORKER_URL}/docx/replace_one",
        headers=_worker_headers(),
        files=files,
        data=form,
        timeout=120,
    )
    _raise_for_worker_response(r)

    b64 = base64.b64encode(r.content).decode("ascii")
    out_name = f"edited_{path.name}"
    return JSONResponse(content={"filename": out_name, "content_type": DOCX_MIME, "content_base64": b64})


@app.post("/docx/replace_one_save", operation_id="docx_replace_one_save")
def docx_replace_one_save(payload: ReplaceOneSaveRequest, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)

    path = _resolve_path(payload.file_path, allowed_exts=(".docx",), require_exact=True)
    data = _read_file(path)

    files = {"file": (path.name, data, DOCX_MIME)}
    form = {"from_text": payload.from_text, "to_text": payload.to_text}

    r = requests.post(
        f"{DOC_WORKER_URL}/docx/replace_one",
        headers=_worker_headers(),
        files=files,
        data=form,
        timeout=180,
    )
    _raise_for_worker_response(r)

    out_name = f"edited_{path.name}"
    saved = _save_bytes(out_name, r.content)
    saved["content_type"] = DOCX_MIME
    saved["source_file"] = str(path.name)
    return saved


@app.post("/docx/delete_last_paragraphs_save", operation_id="docx_delete_last_paragraphs_save")
def docx_delete_last_paragraphs_save(
    payload: DocxDeleteLastParagraphsSaveRequest,
    x_api_key: Optional[str] = Header(default=None),
):
    _require_api_key(x_api_key)

    path = _resolve_path(payload.file_path, allowed_exts=(".docx",), require_exact=True)
    data = _read_file(path)

    files = {"file": (path.name, data, DOCX_MIME)}
    form = {
        "n": str(payload.n),
        "allow_empty_output": "true" if payload.allow_empty_output else "false",
    }

    r = requests.post(
        f"{DOC_WORKER_URL}/docx/delete_last_paragraphs",
        headers=_worker_headers(),
        files=files,
        data=form,
        timeout=180,
    )
    _raise_for_worker_response(r)

    out_name = f"edited_{path.name}"
    saved = _save_bytes(out_name, r.content)
    saved["content_type"] = DOCX_MIME
    saved["source_file"] = str(path.name)
    saved["n_deleted_paragraphs"] = payload.n
    return saved


# -----------------------------
# TEXT: apply_ops_save (new)
# -----------------------------
@app.post("/text/apply_ops_save", operation_id="text_apply_ops_save")
def text_apply_ops_save(payload: TextApplyOpsSaveRequest, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)

    path = _resolve_path(payload.file_path, allowed_exts=(".txt", ".md", ".csv"), require_exact=True)
    data = _read_file(path)

    ext = path.suffix.lower()
    if ext not in (".txt", ".md", ".csv"):
        raise HTTPException(status_code=400, detail="invalid_text_extension")

    files = {"file": (path.name, data, "application/octet-stream")}
    form = {"ops_json": json.dumps(payload.ops, ensure_ascii=False)}

    r = requests.post(
        f"{DOC_WORKER_URL}/text/apply_ops",
        headers=_worker_headers(),
        files=files,
        data=form,
        timeout=180,
    )
    _raise_for_worker_response(r)
    if (not payload.allow_empty_output) and len(r.content) == 0:
        raise HTTPException(
            status_code=400,
            detail="empty_output_blocked_set_allow_empty_output_true_to_override",
        )

    out_name = f"edited_{path.name}"
    saved = _save_bytes(out_name, r.content)
    saved["content_type"] = "text/markdown; charset=utf-8" if ext == ".md" else "text/plain; charset=utf-8"
    saved["source_file"] = str(path.name)
    saved["ops_count"] = len(payload.ops)
    return saved


# -----------------------------
# XLSX: update_cells_save
# -----------------------------
@app.post("/xlsx/update_cells_save", operation_id="xlsx_update_cells_save")
def xlsx_update_cells_save(payload: XlsxUpdateCellsSaveRequest, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)

    if not payload.updates:
        raise HTTPException(status_code=400, detail="updates_required_non_empty")

    path = _resolve_path(payload.file_path, allowed_exts=(".xlsx",), require_exact=True)
    data = _read_file(path)

    files = {"file": (path.name, data, XLSX_MIME)}
    form = {"updates_json": json.dumps(payload.updates, ensure_ascii=False)}

    r = requests.post(
        f"{DOC_WORKER_URL}/xlsx/update_cells",
        headers=_worker_headers(),
        files=files,
        data=form,
        timeout=180,
    )
    _raise_for_worker_response(r)

    out_name = f"edited_{path.name}"
    saved = _save_bytes(out_name, r.content)
    saved["content_type"] = XLSX_MIME
    saved["source_file"] = str(path.name)
    saved["updates_count"] = len(payload.updates)
    return saved


# -----------------------------
# DOCX: to_pdf_save
# -----------------------------
@app.post("/docx/to_pdf_save", operation_id="docx_to_pdf_save")
def docx_to_pdf_save(payload: DocxToPdfSaveRequest, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)

    path = _resolve_path(payload.file_path, allowed_exts=(".docx",), require_exact=True)
    data = _read_file(path)

    files = {"file": (path.name, data, DOCX_MIME)}
    out_name = payload.output_name or f"{Path(path.name).stem}.pdf"
    if not out_name.lower().endswith(".pdf"):
        out_name = f"{out_name}.pdf"

    r = requests.post(
        f"{DOC_WORKER_URL}/docx/to_pdf",
        headers=_worker_headers(),
        files=files,
        data={"filename": out_name},
        timeout=300,
    )
    _raise_for_worker_response(r)

    saved = _save_bytes(out_name, r.content)
    saved["content_type"] = PDF_MIME
    saved["source_file"] = str(path.name)
    saved["conversion"] = "docx_to_pdf"
    return saved


# -----------------------------
# Generic single-file -> Markdown
# -----------------------------
@app.post("/file/to_md_save", operation_id="file_to_md_save")
def file_to_md_save(payload: FileToMdSaveRequest, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)

    path = _resolve_path(
        payload.file_path,
        allowed_exts=(".docx", ".pdf", ".md", ".txt", ".xlsx", ".csv"),
        require_exact=True,
    )
    data = _read_file(path)

    title = (payload.title or "Konvertiert").strip() or "Konvertiert"
    mfiles = [("files", (path.name, data, "application/octet-stream"))]

    r = requests.post(
        f"{DOC_WORKER_URL}/bundle/to_md",
        headers=_worker_headers(),
        files=mfiles,
        data={"title": title, "mode": "raw"},
        timeout=300,
    )
    _raise_for_worker_response(r)

    if payload.output_name:
        out_name = payload.output_name
    else:
        out_name = f"{Path(path.name).stem}.md"
    if not out_name.lower().endswith(".md"):
        out_name = f"{out_name}.md"

    saved = _save_bytes(out_name, r.content)
    saved["content_type"] = "text/markdown; charset=utf-8"
    saved["source_file"] = str(path.name)
    saved["conversion"] = "file_to_md"
    return saved


# -----------------------------
# PDF: remove_pages_save + merge_save (new)
# -----------------------------
@app.post("/pdf/remove_pages_save", operation_id="pdf_remove_pages_save")
def pdf_remove_pages_save(payload: PdfRemovePagesSaveRequest, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)

    path = _resolve_path(payload.file_path, allowed_exts=(".pdf",), require_exact=True)
    data = _read_file(path)

    files = {"file": (path.name, data, PDF_MIME)}
    form = {"remove_pages_json": json.dumps(payload.remove_pages)}

    r = requests.post(
        f"{DOC_WORKER_URL}/pdf/remove_pages",
        headers=_worker_headers(),
        files=files,
        data=form,
        timeout=180,
    )
    _raise_for_worker_response(r)

    out_name = f"edited_{path.name}"
    saved = _save_bytes(out_name, r.content)
    saved["content_type"] = PDF_MIME
    saved["source_file"] = str(path.name)
    saved["removed_pages"] = payload.remove_pages
    return saved


@app.post("/pdf/merge_save", operation_id="pdf_merge_save")
def pdf_merge_save(payload: PdfMergeSaveRequest, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)

    if not payload.file_paths or len(payload.file_paths) < 2:
        raise HTTPException(status_code=400, detail="provide_at_least_2_pdfs")

    paths: list[Path] = []
    for fp in payload.file_paths:
        _reject_wildcards(fp or "")
        p = _resolve_path(
            fp,
            allowed_exts=(".pdf",),
            require_exact=True,
            preferred_exact_paths=payload.attachment_exact_paths,
        )
        paths.append(p)

    mfiles = []
    for p in paths:
        b = _read_file(p)
        mfiles.append(("files", (p.name, b, PDF_MIME)))

    r = requests.post(
        f"{DOC_WORKER_URL}/pdf/merge",
        headers=_worker_headers(),
        files=mfiles,
        data={"debug_meta": "false"},
        timeout=300,
    )
    _raise_for_worker_response(r)

    out_name = payload.output_name or "merged.pdf"
    if not out_name.lower().endswith(".pdf"):
        out_name = f"{out_name}.pdf"

    saved = _save_bytes(out_name, r.content)
    saved["content_type"] = PDF_MIME
    saved["source_files"] = [p.name for p in paths]
    return saved


# -----------------------------
# Bundle to Markdown (existing + strict handling)
# -----------------------------
@app.post("/bundle/to_md", include_in_schema=False)
def bundle_to_md(payload: BundleToMdRequest, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)

    if REQUIRE_EXACT_FILE_PATH and not payload.file_paths:
        raise HTTPException(status_code=400, detail="file_paths_required_in_strict_mode")

    title = (payload.title or "Masterkontext").strip() or "Masterkontext"

    paths: list[Path] = []
    if payload.file_paths:
        for fp in payload.file_paths:
            _reject_wildcards(fp or "")
            p = _resolve_path(fp, allowed_exts=(".docx", ".pdf", ".md", ".txt", ".xlsx", ".csv"))
            paths.append(p)
    else:
        # backwards-compatible best-effort
        for ext in ("docx", "pdf", "md", "txt", "xlsx", "csv"):
            try:
                paths.append(_pick_latest_file_by_exts((f".{ext}",)))
            except Exception:
                pass

    if not paths:
        raise HTTPException(status_code=400, detail="No input files found/provided.")

    mfiles = []
    for p in paths:
        b = _read_file(p)
        mfiles.append(("files", (p.name, b, "application/octet-stream")))

    r = requests.post(
        f"{DOC_WORKER_URL}/bundle/to_md",
        headers=_worker_headers(),
        files=mfiles,
        data={"title": title, "mode": "rag_mastercontext"},
        timeout=300,
    )
    _raise_for_worker_response(r)

    return Response(
        content=r.content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=masterkontext.md"},
    )


@app.post("/bundle/to_md_save", operation_id="bundle_to_md_save")
def bundle_to_md_save(payload: BundleToMdSaveRequest, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)

    title = (payload.title or "Masterkontext").strip() or "Masterkontext"

    paths: list[Path] = []
    if payload.file_paths:
        for fp in payload.file_paths:
            _reject_wildcards(fp or "")
            p = _resolve_path(
                fp,
                allowed_exts=(".docx", ".pdf", ".md", ".txt", ".xlsx", ".csv"),
                require_exact=True,
            )
            paths.append(p)

    if not paths:
        raise HTTPException(status_code=400, detail="No input files found/provided.")

    mfiles = []
    for p in paths:
        b = _read_file(p)
        mfiles.append(("files", (p.name, b, "application/octet-stream")))

    r = requests.post(
        f"{DOC_WORKER_URL}/bundle/to_md",
        headers=_worker_headers(),
        files=mfiles,
        data={"title": title, "mode": "rag_mastercontext"},
        timeout=300,
    )
    _raise_for_worker_response(r)

    safe_title = _sanitize_filename(title)
    out_name = safe_title if safe_title.lower().endswith(".md") else f"{safe_title}.md"

    saved = _save_bytes(out_name, r.content)
    saved["content_type"] = "text/markdown; charset=utf-8"
    saved["source_files"] = [p.name for p in paths]
    return saved
