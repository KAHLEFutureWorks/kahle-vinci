from __future__ import annotations

import base64
import asyncio
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
import unicodedata
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import quote

import requests
from docx import Document
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import (
    FileResponse, HTMLResponse, RedirectResponse, Response as FastAPIResponse,
)
from pydantic import BaseModel, Field
from pypdf import PdfReader


try:
    from .portal_governance import (
        GovernanceError,
        PortalGovernance,
        SQLiteGovernanceStore,
        serialize as serialize_governance,
    )
except ImportError:  # pragma: no cover - supports the existing file-based contract harness
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from portal_governance import (  # type: ignore[no-redef]
        GovernanceError,
        PortalGovernance,
        SQLiteGovernanceStore,
        serialize as serialize_governance,
    )

try:
    from .step_up_auth import (
        LocalStepUpAdapter, MicrosoftOIDCAdapter, StepUpAuthority, StepUpError,
    )
except ImportError:  # pragma: no cover
    from step_up_auth import (
        LocalStepUpAdapter, MicrosoftOIDCAdapter, StepUpAuthority, StepUpError,
    )

try:
    from .document_lifecycle import Analysis, DocumentLifecycle, LifecycleError, workdays_until
    from .audit_export import AuditExporter
    from .maintenance import MaintenanceError, MaintenanceService
    from .quality_cases import QualityCaseError, QualityCaseService
    from .legacy_migration import LegacyMigrationService
    from .markdown_correction import IonosMarkdownCorrector, MarkdownCorrectionError, MarkdownCorrectionService
    from .quality_dashboard import QualityDashboard
    from .document_changes import DocumentChangeError, DocumentChangeService
    from .ownership import OwnershipError, OwnershipService
    from .upload_jobs import UploadJobError, UploadJobService
    from .document_authority import AuthorityError, DocumentAuthorityService
    from .rag_metadata import RAGMetadataWriter
    from .content_classification import ContentConfidentialityClassifier
    from .global_analysis import (
        CorpusDocument, GlobalAnalysisError, GlobalCorpus, GlobalDocumentAnalyzer, IonosEmbeddingProvider,
    )
    from .secure_ingest import (
        ClamAVScanner, DocumentWorkerAdapter, IngestError, PromptInjectionInspector,
        QuarantineStorage, ScreenshotInspector, SecureFileInspector, SecureIngestPipeline,
    )
except ImportError:  # pragma: no cover
    from document_lifecycle import Analysis, DocumentLifecycle, LifecycleError, workdays_until
    from audit_export import AuditExporter
    from maintenance import MaintenanceError, MaintenanceService
    from quality_cases import QualityCaseError, QualityCaseService
    from legacy_migration import LegacyMigrationService
    from markdown_correction import IonosMarkdownCorrector, MarkdownCorrectionError, MarkdownCorrectionService
    from quality_dashboard import QualityDashboard
    from document_changes import DocumentChangeError, DocumentChangeService
    from ownership import OwnershipError, OwnershipService
    from upload_jobs import UploadJobError, UploadJobService
    from document_authority import AuthorityError, DocumentAuthorityService
    from rag_metadata import RAGMetadataWriter
    from content_classification import ContentConfidentialityClassifier
    from global_analysis import (
        CorpusDocument, GlobalAnalysisError, GlobalCorpus, GlobalDocumentAnalyzer, IonosEmbeddingProvider,
    )
    from secure_ingest import (
        ClamAVScanner, DocumentWorkerAdapter, IngestError, PromptInjectionInspector,
        QuarantineStorage, ScreenshotInspector, SecureFileInspector, SecureIngestPipeline,
    )

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
KB_SYNC_INTERNAL_API_KEY = os.getenv("KB_SYNC_INTERNAL_API_KEY", MAINTENANCE_API_KEY).strip()
PORTAL_ALLOWED_EMAIL_DOMAINS = {
    item.strip().casefold() for item in os.getenv("PORTAL_ALLOWED_EMAIL_DOMAINS", "kahle.de").split(",")
    if item.strip()
}
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
PORTAL_DB_PATH = Path(
    os.getenv("KB_PORTAL_DB_PATH", "/portal-data/wissensportal.sqlite3")
).resolve()
PORTAL_GOVERNANCE = PortalGovernance(SQLiteGovernanceStore(PORTAL_DB_PATH))
DOCUMENT_LIFECYCLE = DocumentLifecycle(PORTAL_GOVERNANCE.store, PORTAL_GOVERNANCE)
MAINTENANCE = MaintenanceService(PORTAL_GOVERNANCE.store)
AUDIT_EXPORTER = AuditExporter(PORTAL_GOVERNANCE.store)
QUALITY_CASES = QualityCaseService(PORTAL_GOVERNANCE.store)
DOCUMENT_CHANGES = DocumentChangeService(PORTAL_GOVERNANCE.store, PORTAL_GOVERNANCE)
OWNERSHIP = OwnershipService(PORTAL_GOVERNANCE.store, PORTAL_GOVERNANCE)
UPLOAD_JOBS = UploadJobService(PORTAL_GOVERNANCE.store)
DOCUMENT_AUTHORITY = DocumentAuthorityService(PORTAL_GOVERNANCE.store, PORTAL_GOVERNANCE)
GLOBAL_CORPUS = GlobalCorpus(PORTAL_GOVERNANCE.store)
GLOBAL_ANALYZER = GlobalDocumentAnalyzer(
    GLOBAL_CORPUS,
    IonosEmbeddingProvider(IONOS_BASE_URL, IONOS_API_KEY, EMBEDDING_MODEL) if IONOS_API_KEY else None,
)
PORTAL_FILES_ROOT = Path(os.getenv("KB_PORTAL_FILES_ROOT", "/portal-data/files"))
RAG_METADATA = RAGMetadataWriter(PORTAL_GOVERNANCE.store, PORTAL_FILES_ROOT)
CONFIDENTIALITY_CLASSIFIER = ContentConfidentialityClassifier()
SECURE_INGEST = SecureIngestPipeline(
    SecureFileInspector(max_bytes=MAX_UPLOAD_BYTES),
    ClamAVScanner(host=os.getenv("KB_CLAMAV_HOST", "clamav"), port=int(os.getenv("KB_CLAMAV_PORT", "3310"))),
    DocumentWorkerAdapter(os.getenv("DOCUMENT_WORKER_URL", "http://document-worker:8090"), os.getenv("DOCUMENT_WORKER_API_KEY", "")),
    QuarantineStorage(PORTAL_FILES_ROOT),
    PromptInjectionInspector(),
)
LEGACY_MIGRATION = LegacyMigrationService(
    PORTAL_GOVERNANCE, DOCUMENT_LIFECYCLE, GLOBAL_ANALYZER, GLOBAL_CORPUS,
    QuarantineStorage(PORTAL_FILES_ROOT),
)
MARKDOWN_CORRECTION = MarkdownCorrectionService(
    PORTAL_GOVERNANCE, DOCUMENT_LIFECYCLE, GLOBAL_ANALYZER, GLOBAL_CORPUS,
    QuarantineStorage(PORTAL_FILES_ROOT),
    IonosMarkdownCorrector(
        IONOS_BASE_URL, IONOS_API_KEY,
        os.getenv("IONOS_CHAT_MODEL_DEFAULT", "mistralai/Mistral-Small-24B-Instruct"),
    ) if IONOS_API_KEY else None,
)
QUALITY_DASHBOARD = QualityDashboard(PORTAL_GOVERNANCE.store, Path(os.getenv("KB_BACKUP_STATE_PATH", "/backups/primary/backup-state.json")))
STEP_UP_AUTHORITY: StepUpAuthority | None = None
_STEP_UP_SECRET = os.getenv("KB_PORTAL_STEP_UP_SECRET", "").strip()
_ENTRA_TENANT_ID = os.getenv("KB_PORTAL_ENTRA_TENANT_ID", "").strip()
_ENTRA_CLIENT_ID = os.getenv("KB_PORTAL_ENTRA_CLIENT_ID", "").strip()
_ENTRA_CLIENT_SECRET = os.getenv("KB_PORTAL_ENTRA_CLIENT_SECRET", "").strip()
_ENTRA_REDIRECT_URI = os.getenv("KB_PORTAL_ENTRA_REDIRECT_URI", "").strip()
if all(
    (
        _STEP_UP_SECRET,
        _ENTRA_TENANT_ID,
        _ENTRA_CLIENT_ID,
        _ENTRA_CLIENT_SECRET,
        _ENTRA_REDIRECT_URI,
    )
):
    STEP_UP_AUTHORITY = StepUpAuthority(
        PORTAL_GOVERNANCE.store,
        MicrosoftOIDCAdapter(
            tenant_id=_ENTRA_TENANT_ID,
            client_id=_ENTRA_CLIENT_ID,
            client_secret=_ENTRA_CLIENT_SECRET,
            redirect_uri=_ENTRA_REDIRECT_URI,
        ),
        signing_secret=_STEP_UP_SECRET,
    )
elif (
    os.getenv("KB_PORTAL_LOCAL_STEP_UP", "false").strip().lower() == "true"
    and _STEP_UP_SECRET
    # Fail closed: sobald irgendeine Entra-Angabe existiert, ist die Umgebung
    # nicht mehr rein lokal und der Ersatzadapter darf nicht greifen.
    and not any(
        (_ENTRA_TENANT_ID, _ENTRA_CLIENT_ID, _ENTRA_CLIENT_SECRET, _ENTRA_REDIRECT_URI)
    )
):
    STEP_UP_AUTHORITY = StepUpAuthority(
        PORTAL_GOVERNANCE.store,
        LocalStepUpAdapter(
            confirm_url="/wissen/api/portal/auth/step-up/local-confirm",
            signing_secret=_STEP_UP_SECRET,
        ),
        signing_secret=_STEP_UP_SECRET,
    )
    print(
        "WARNUNG: lokale Step-up-Bestaetigung aktiv. Rollen und Rechte werden "
        "weiterhin geprueft, die zweite Microsoft-Anmeldung jedoch nicht. "
        "Nur fuer die lokale Abnahme zulaessig.",
        flush=True,
    )


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


class PortalRoleRequest(BaseModel):
    role: str = Field(..., pattern=r"^(employee|manager|admin|portal_admin)$")


class PortalActivationRequest(BaseModel):
    active: bool


class PortalManagerRequest(BaseModel):
    manager_user_id: str | None = None


class PortalDelegationRequest(BaseModel):
    manager_user_id: str = Field(..., min_length=1, max_length=100)
    delegate_user_id: str = Field(..., min_length=1, max_length=100)
    valid_from: str | None = None
    valid_until: str | None = None


class PortalAbsenceRequest(BaseModel):
    manager_user_id: str = Field(..., min_length=1, max_length=100)
    absent_from: str | None = None
    absent_until: str | None = None
    reason: str = Field(..., max_length=1000)


class PortalAccessRequest(BaseModel):
    knowledgebase_id: str = Field(..., min_length=1, max_length=100)
    can_read: bool
    can_upload: bool


class PortalRagFeedbackRequest(BaseModel):
    reason: str = Field(..., max_length=60)
    comment: str = Field("", max_length=2000)
    question: str = Field(..., max_length=8000)
    answer: str = Field(..., max_length=16000)
    sources: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    passages: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    runtime: dict[str, Any] = Field(default_factory=dict)
    request_id: str = Field(..., min_length=1, max_length=200)


class PortalIncidentCommentRequest(BaseModel):
    comment: str = Field(..., min_length=3, max_length=2000)


class PortalMigrationStageRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)


class PortalMigrationMetadataRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    owner_email: str = Field(..., min_length=3, max_length=320)
    confidentiality: str = Field(..., pattern=r"^(internal|restricted|confidential)$")
    authority_type: str = Field(..., min_length=3, max_length=80)
    authority_level: int = Field(..., ge=1, le=6)
    scope: dict[str, Any] = Field(default_factory=dict)


class PortalMarkdownRevisionRequest(BaseModel):
    instruction: str = Field("", max_length=4000)
    replacement_markdown: str = Field("", max_length=2_000_000)
    reason: str = Field(..., min_length=3, max_length=2000)
    confirmed: bool


class PortalRemovalRequest(BaseModel):
    document_id: str = Field(..., min_length=1, max_length=100)
    kind: str = Field(..., pattern=r"^(deactivate|delete)$")
    reason: str = Field(..., min_length=3, max_length=2000)


class PortalRemovalDecisionRequest(BaseModel):
    approve: bool
    reason: str = Field(..., min_length=3, max_length=2000)


class PortalRestoreRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=2000)


class PortalLegalHoldRequest(BaseModel):
    enabled: bool
    reason: str = Field(..., min_length=3, max_length=2000)
    review_at: str | None = None


class PortalRenewalRequest(BaseModel):
    document_id: str = Field(..., min_length=1, max_length=100)
    reason: str = Field(..., min_length=3, max_length=2000)
    confirmed: bool


class PortalConfidentialityRequest(BaseModel):
    document_id: str = Field(..., min_length=1, max_length=100)
    desired: str = Field(..., pattern=r"^(internal|restricted|confidential)$")
    reason: str = Field(..., min_length=3, max_length=2000)


class PortalDocumentChangeDecisionRequest(BaseModel):
    approve: bool
    reason: str = Field(..., min_length=3, max_length=2000)


class PortalOwnershipProposalRequest(BaseModel):
    proposed_owner_user_id: str = Field(..., min_length=1, max_length=200)
    reason: str = Field(..., min_length=3, max_length=2000)


class PortalOwnerPermissionRequest(BaseModel):
    allowed: bool


class PortalAuthorityRequest(BaseModel):
    authority_type: str = Field(..., min_length=3, max_length=80)
    scope: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(..., min_length=3, max_length=2000)


class PortalAuthorityRelationRequest(BaseModel):
    target_document_id: str = Field(..., min_length=1, max_length=100)
    relation_type: str = Field(..., pattern=r"^(supersedes|overrides|applies_only_if|related_to)$")
    condition_text: str = Field("", max_length=2000)
    reason: str = Field(..., min_length=3, max_length=2000)


class PortalOwnershipConfirmationRequest(BaseModel):
    accept: bool
    reason: str = Field(..., min_length=3, max_length=2000)


class PortalKnowledgebaseChangeRequest(BaseModel):
    kind: str = Field(..., pattern=r"^(create|rename|archive|delete)$")
    knowledgebase_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

class PortalKnowledgebaseDecisionRequest(BaseModel):
    approve: bool
    reason: str = Field(..., min_length=3, max_length=1000)

class PortalRetrievalScopeRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=200)


class PortalCaseActionRequest(BaseModel):
    action: str = Field(..., pattern=r"^(create|replace|publish_existing|discard)$")
    target_document_id: str | None = Field(None, max_length=100)


class PortalCaseDecisionRequest(BaseModel):
    decision: str = Field(..., pattern=r"^(approve|reject|escalate)$")
    reason: str = Field(..., min_length=3, max_length=2000)


class PortalUploadResponse(BaseModel):
    case_id: str
    document_id: str
    version_id: str
    status: str
    owner_email: str
    prompt_injection_risk: str
    confidentiality: str
    confidentiality_reason: str
    requires_admin: bool
    owner_confirmation_required: bool = False
    conversion_quality: str = "good"
    conversion_issues: list[str] = Field(default_factory=list)
    exact_duplicate_document_id: str | None = None
    matches: list[dict[str, Any]] = Field(default_factory=list)


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


def require_openwebui_user(request: Request) -> dict[str, Any]:
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
    return user


def require_admin(request: Request) -> dict[str, Any]:
    user = require_openwebui_user(request)
    if str(user.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="admin_role_required")
    return user


def require_portal_identity(
    user: dict[str, Any] = Depends(require_openwebui_user),
) -> dict[str, Any]:
    user_id = str(user.get("id") or "").strip()
    email = str(user.get("email") or "").strip()
    display_name = str(user.get("name") or user.get("display_name") or email).strip()
    if not user_id or not email:
        raise HTTPException(status_code=502, detail="openwebui_identity_incomplete")
    email_domain = email.rsplit("@", 1)[-1].casefold() if "@" in email else ""
    if not DEV_AUTH_BYPASS and email_domain not in PORTAL_ALLOWED_EMAIL_DOMAINS:
        raise HTTPException(status_code=403, detail="kahle_microsoft_tenant_required")
    try:
        identity = PORTAL_GOVERNANCE.sync_identity(
            user_id=user_id,
            email=email,
            display_name=display_name,
            active=True,
            bootstrap_portal_admin=str(user.get("role") or "").lower() == "admin",
        )
    except GovernanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not identity.active:
        raise HTTPException(status_code=403, detail="portal_user_inactive")
    return {**serialize_governance(identity), "openwebui_role": user.get("role")}


def require_fresh_step_up(request: Request, identity: dict[str, Any]) -> None:
    if DEV_AUTH_BYPASS:
        return
    if STEP_UP_AUTHORITY is None:
        raise HTTPException(status_code=503, detail="microsoft_step_up_not_configured")
    proof = request.cookies.get(StepUpAuthority.COOKIE_NAME, "")
    try:
        STEP_UP_AUTHORITY.verify(proof, user_id=identity["user_id"])
    except StepUpError as exc:
        raise HTTPException(
            status_code=428,
            detail="fresh_microsoft_authentication_required",
        ) from exc
    PORTAL_GOVERNANCE.record_audit(
        identity["user_id"], "step_up_verified", "user", identity["user_id"], {}
    )

def _portal_call(call: Callable[[], Any], *, forbidden_status: int = 403) -> Any:
    try:
        return call()
    except GovernanceError as exc:
        detail = str(exc)
        status = 404 if detail.startswith("unknown_") else 409 if detail.endswith("_required") else forbidden_status
        raise HTTPException(status_code=status, detail=detail) from exc

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
            headers={"X-API-Key": KB_SYNC_INTERNAL_API_KEY},
            timeout=180,
        )
        if response.status_code >= 400:
            return {"ok": False, "error": f"kb_sync_http_{response.status_code}"}
        payload = response.json()
        return payload if isinstance(payload, dict) else {"ok": True}
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def _trigger_hybrid_reindex() -> dict[str, Any]:
    try:
        response = requests.post(
            f"{KB_SYNC_URL}/reindex-all",
            headers={"X-API-Key": KB_SYNC_INTERNAL_API_KEY},
            timeout=300,
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



@app.post("/portal/internal/retrieval-scope")
def portal_internal_retrieval_scope(
    payload: PortalRetrievalScopeRequest,
    x_api_key: str = Header(default="", alias="X-API-Key"),
) -> dict[str, Any]:
    if not MAINTENANCE_API_KEY or not hmac.compare_digest(x_api_key, MAINTENANCE_API_KEY):
        raise HTTPException(status_code=401, detail="internal_api_key_required")
    try:
        identity = PORTAL_GOVERNANCE.identity(payload.user_id)
        if not identity.active:
            raise GovernanceError("portal_user_inactive")
        knowledgebase_ids = PORTAL_GOVERNANCE.allowed_knowledgebases(payload.user_id, "read")
    except GovernanceError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not knowledgebase_ids:
        raise HTTPException(status_code=403, detail="no_readable_knowledgebases")
    with PORTAL_GOVERNANCE.store.connect() as db:
        placeholders = ",".join("?" for _ in knowledgebase_ids)
        active_version_ids = [row["active_version_id"] for row in db.execute(
            f"""SELECT DISTINCT d.active_version_id FROM canonical_documents d
                 JOIN document_versions v ON v.version_id=d.active_version_id AND v.status='active'
                 JOIN document_publications p ON p.document_id=d.document_id AND p.status='active'
                 WHERE p.knowledgebase_id IN ({placeholders}) AND v.valid_from <= ? AND v.valid_until >= ?""",
            (*knowledgebase_ids, date.today().isoformat(), date.today().isoformat()),
        ).fetchall()]
    if not active_version_ids:
        raise HTTPException(status_code=403, detail="no_active_readable_versions")
    return {"user_id": identity.user_id, "knowledgebase_ids": knowledgebase_ids,
            "active_version_ids": active_version_ids}


@app.get("/portal/session")
def portal_session(
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    return identity


@app.get("/portal/knowledgebases")
def portal_knowledgebases(
    access: str = "read",
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    if access not in {"read", "upload"}:
        raise HTTPException(status_code=400, detail="invalid_access_kind")
    try:
        knowledgebases = PORTAL_GOVERNANCE.list_knowledgebases(identity["user_id"], access)
    except GovernanceError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "access": access,
        "knowledgebases": serialize_governance(knowledgebases),
    }

@app.get("/portal/documents")
def portal_list_documents(
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    readable = PORTAL_GOVERNANCE.allowed_knowledgebases(identity["user_id"], "read")
    with PORTAL_GOVERNANCE.store.connect() as db:
        rows = db.execute(
            """SELECT DISTINCT d.document_id, d.title, d.owner_user_id, d.active_version_id,
                              v.status, v.valid_until, p.knowledgebase_id
               FROM canonical_documents d
               LEFT JOIN document_versions v ON v.version_id=d.active_version_id
               LEFT JOIN document_publications p ON p.document_id=d.document_id
               WHERE d.owner_user_id=? OR p.knowledgebase_id IN ({})
               ORDER BY d.updated_at DESC""".format(",".join("?" for _ in readable) or "NULL"),
            (identity["user_id"], *readable),
        ).fetchall()
    return {"documents": [dict(row) for row in rows]}


@app.get("/portal/admin/knowledgebase-overview")
def portal_admin_knowledgebase_overview(
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    """
    Verwaltungssicht auf Wissensbereiche und ihre Dokumente.

    Bewusst getrennt von /portal/documents: Dort filtern die Leserechte, hier
    verwaltet ein Admin die Struktur und braucht auch Bereiche, in die er selbst
    nicht hineinlesen darf. Zurueckgegeben werden ausschliesslich Metadaten,
    niemals Dokumentinhalte, und Owner erscheinen mit Anzeigenamen statt roher
    Benutzer-ID.
    """
    if identity["role"] not in {"admin", "portal_admin"}:
        raise HTTPException(status_code=403, detail="admin_required")
    with PORTAL_GOVERNANCE.store.connect() as db:
        bases = db.execute(
            "SELECT knowledgebase_id, slug, label, purpose, status FROM knowledgebases"
            " ORDER BY label"
        ).fetchall()
        documents = db.execute(
            """SELECT p.knowledgebase_id, d.document_id, d.title, d.owner_user_id,
                      COALESCE(u.display_name, d.owner_user_id) AS owner_name,
                      COALESCE(v.status, 'draft') AS status, v.valid_until
               FROM document_publications p
               JOIN canonical_documents d ON d.document_id = p.document_id
               LEFT JOIN document_versions v ON v.version_id = d.active_version_id
               LEFT JOIN portal_users u ON u.user_id = d.owner_user_id
               ORDER BY d.title"""
        ).fetchall()

    by_base: dict[str, list[dict[str, Any]]] = {}
    for row in documents:
        by_base.setdefault(row["knowledgebase_id"], []).append({
            key: row[key] for key in
            ("document_id", "title", "owner_name", "status", "valid_until")
        })

    overview = []
    for base in bases:
        entries = by_base.get(base["knowledgebase_id"], [])
        counts: dict[str, int] = {}
        for entry in entries:
            counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        overview.append({
            **{key: base[key] for key in ("knowledgebase_id", "slug", "label", "purpose", "status")},
            "document_count": len(entries),
            "status_counts": counts,
            "documents": entries,
        })
    unassigned = sum(1 for row in documents if row["knowledgebase_id"] is None)
    return {"knowledgebases": overview, "unpublished_documents": unassigned}


def _resolve_valid_workdays(valid_workdays: int | None, valid_until: str | None) -> int:
    """
    PRD 17.1 laesst zwei gleichwertige Eingaben zu: Arbeitstage oder ein
    geprueftes Datum. Genau eine davon muss gesetzt sein; das Datum wird
    serverseitig umgerechnet, damit die niedersaechsischen Feiertage und die
    Grenze von 60 Arbeitstagen verbindlich bleiben.
    """
    if (valid_workdays is None) == (valid_until is None):
        raise HTTPException(status_code=422, detail="valid_workdays_or_valid_until_required")
    if valid_workdays is not None:
        return valid_workdays
    try:
        target = date.fromisoformat(valid_until or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_valid_until") from exc
    try:
        return workdays_until(date.today(), target)
    except LifecycleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/portal/documents", response_model=PortalUploadResponse, status_code=201)
async def portal_upload_document(
    file: UploadFile = File(...),
    knowledgebase_id: str = Form(...),
    title: str = Form(..., min_length=2, max_length=300),
    valid_workdays: int | None = Form(None, ge=1, le=60),
    valid_until: str | None = Form(None),
    confidentiality: str = Form("internal"),
    owner_user_id: str | None = Form(None),
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> PortalUploadResponse:
    valid_workdays = _resolve_valid_workdays(valid_workdays, valid_until)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")
    filename = file.filename or ""
    intended_owner_user_id = owner_user_id or identity["user_id"]
    try:
        if intended_owner_user_id != identity["user_id"]:
            if not OWNERSHIP.may_propose_other(identity["user_id"]):
                raise GovernanceError("owner_proposal_permission_required")
            if not PORTAL_GOVERNANCE.identity(intended_owner_user_id).active:
                raise GovernanceError("owner_inactive")
        inspected = SECURE_INGEST.inspector.inspect(filename, data)
        document_id = str(uuid.uuid4())
        submission = DOCUMENT_LIFECYCLE.submit(
            uploaded_by_user_id=identity["user_id"], owner_user_id=identity["user_id"],
            target_knowledgebase_id=knowledgebase_id, title=title, original_filename=filename,
            original_file_id=f"portal://documents/{document_id}", original_sha256=inspected.sha256,
            valid_workdays=valid_workdays, confidentiality=confidentiality, document_id=document_id,
        )
        result = SECURE_INGEST.ingest(submission.document_id, submission.version_id, filename, data, title)
        confidentiality_suggestion = CONFIDENTIALITY_CLASSIFIER.classify(
            result.markdown_path.read_text(encoding="utf-8")
        )
        submission = DOCUMENT_LIFECYCLE.apply_automatic_confidentiality(
            case_id=submission.case_id, level=confidentiality_suggestion.level,
            reason=confidentiality_suggestion.reason, signals=confidentiality_suggestion.signals,
        )
        global_result = GLOBAL_ANALYZER.analyze(
            version_id=submission.version_id, title=title,
            markdown=result.markdown_path.read_text(encoding="utf-8"),
        )
        material_matches = tuple(match for match in global_result.matches if match.level in {"identical", "very_high", "medium"})
        cross_kb_matches = tuple(
            match.document_id for match in material_matches if knowledgebase_id not in match.knowledgebase_ids
        )
        same_kb_levels = [match.level for match in material_matches if knowledgebase_id in match.knowledgebase_ids]
        same_kb_similarity = next((level for level in ("very_high", "medium") if level in same_kb_levels), "none")
        submission = DOCUMENT_LIFECYCLE.record_analysis(
            case_id=submission.case_id, normalized_sha256=global_result.normalized_sha256,
            markdown_sha256=result.markdown_sha256,
            analysis=Analysis(
                exact_duplicate_document_id=global_result.exact_document_id,
                same_kb_similarity=same_kb_similarity, cross_kb_matches=cross_kb_matches,
                contradiction_document_ids=global_result.contradiction_document_ids,
                version_candidate_document_ids=tuple(
                    match.document_id for match in material_matches if match.version_candidate
                ),
                prompt_injection_risk=result.injection.risk,
                conversion_quality=result.conversion_quality,
                notes=result.conversion_issues,
            ),
        )
        RAG_METADATA.write(submission.version_id, result.markdown_path)
        GLOBAL_CORPUS.upsert(CorpusDocument(
            submission.document_id, submission.version_id, title,
            result.markdown_path.read_text(encoding="utf-8"), (knowledgebase_id,),
            "pending" if submission.status == "pending_employee_decision" else "quarantine",
        ))
        if intended_owner_user_id != identity["user_id"]:
            OWNERSHIP.create_initial_proposal(
                submission.document_id, submission.case_id, identity["user_id"], intended_owner_user_id,
            )
            submission = DOCUMENT_LIFECYCLE.submission(submission.case_id)
    except GovernanceError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LifecycleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IngestError as exc:
        code = str(exc)
        if code in {"malware_scanner_unavailable", "malware_scan_failed",
                    "document_conversion_failed", "document_conversion_empty"}:
            incident_id = _notify_system_error("required_ingest_check", {"error_code": code})
            raise HTTPException(status_code=503, detail=f"required_check_unavailable:{incident_id}") from exc
        raise HTTPException(status_code=422, detail=code) from exc
    except GlobalAnalysisError as exc:
        incident_id = _notify_system_error("global_document_analysis", {"error_code": str(exc)})
        raise HTTPException(status_code=503, detail=f"required_check_unavailable:{incident_id}") from exc
    except Exception as exc:
        incident_id = _notify_system_error("portal_upload", {"error_type": type(exc).__name__})
        print(f"portal_upload_failed incident={incident_id} error={exc}", flush=True)
        raise HTTPException(status_code=500, detail=f"system_error:{incident_id}") from exc
    return PortalUploadResponse(
        case_id=submission.case_id, document_id=submission.document_id,
        version_id=submission.version_id, status=submission.status,
        owner_email=PORTAL_GOVERNANCE.identity(intended_owner_user_id).email,
        owner_confirmation_required=intended_owner_user_id != identity["user_id"],
        prompt_injection_risk=result.injection.risk,
        conversion_quality=result.conversion_quality,
        conversion_issues=list(result.conversion_issues),
        confidentiality=DOCUMENT_LIFECYCLE.submission(submission.case_id).confidentiality,
        confidentiality_reason=confidentiality_suggestion.reason,
        requires_admin=submission.requires_admin,
        exact_duplicate_document_id=global_result.exact_document_id,
        matches=[{
            "document_id": match.document_id, "title": match.title, "level": match.level,
            "knowledgebase_ids": list(match.knowledgebase_ids), "version_candidate": match.version_candidate,
            "has_conflict": bool(match.conflicting_passages),
        } for match in material_matches],
    )


def _run_portal_upload_job(
    job_id: str, data: bytes, filename: str, knowledgebase_id: str, title: str,
    valid_workdays: int, confidentiality: str, owner_user_id: str | None,
    identity: dict[str, Any],
) -> None:
    try:
        UPLOAD_JOBS.progress(job_id, "security", 20)
        UPLOAD_JOBS.progress(job_id, "conversion", 45)
        upload = UploadFile(file=io.BytesIO(data), filename=filename)
        result = asyncio.run(portal_upload_document(
            file=upload, knowledgebase_id=knowledgebase_id, title=title,
            # Die Gueltigkeit ist beim Anlegen des Jobs bereits in Arbeitstage
            # aufgeloest. valid_until muss trotzdem ausdruecklich None sein:
            # Beim direkten Funktionsaufruf greift sonst der Form(None)-Default,
            # und das ist ein FieldInfo-Objekt, nicht None.
            valid_workdays=valid_workdays, valid_until=None,
            confidentiality=confidentiality,
            owner_user_id=owner_user_id, identity=identity,
        ))
        UPLOAD_JOBS.progress(job_id, "comparison", 90)
        UPLOAD_JOBS.complete(job_id, result.model_dump())
    except HTTPException as exc:
        UPLOAD_JOBS.fail(job_id, str(exc.detail))
    except Exception as exc:  # pragma: no cover - final fail-safe for worker failures
        incident_id = _notify_system_error("portal_upload_job", {"error_type": type(exc).__name__})
        UPLOAD_JOBS.fail(job_id, f"system_error:{incident_id}")


@app.post("/portal/upload-jobs", status_code=202)
async def portal_create_upload_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...), knowledgebase_id: str = Form(...),
    title: str = Form(..., min_length=2, max_length=300),
    valid_workdays: int | None = Form(None, ge=1, le=60),
    valid_until: str | None = Form(None),
    confidentiality: str = Form("internal"),
    owner_user_id: str | None = Form(None),
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    valid_workdays = _resolve_valid_workdays(valid_workdays, valid_until)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")
    try:
        PORTAL_GOVERNANCE.require_access(identity["user_id"], knowledgebase_id, "upload")
    except GovernanceError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    job_id = UPLOAD_JOBS.create(identity["user_id"])
    background_tasks.add_task(
        _run_portal_upload_job, job_id, data, file.filename or "", knowledgebase_id,
        title, valid_workdays, confidentiality, owner_user_id, identity,
    )
    return {"job_id": job_id, "status": "queued", "step": "uploaded", "progress": 5}


@app.get("/portal/upload-jobs/{job_id}")
def portal_get_upload_job(
    job_id: str, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        return UPLOAD_JOBS.get(
            job_id, identity["user_id"], identity["role"] in {"admin", "portal_admin"}
        )
    except UploadJobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/portal/feedback/context")
def portal_feedback_context(
    chat_id: str, message_id: str, request: Request,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    del identity
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", chat_id) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", message_id):
        raise HTTPException(status_code=400, detail="invalid_feedback_reference")
    headers = {}
    if request.headers.get("Authorization"):
        headers["Authorization"] = request.headers["Authorization"]
    if request.headers.get("Cookie"):
        headers["Cookie"] = request.headers["Cookie"]
    try:
        response = requests.get(f"{OPENWEBUI_URL}/api/v1/chats/{chat_id}", headers=headers, timeout=20)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="chat_context_unavailable") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="chat_context_not_available")
    chat = response.json().get("chat") or response.json()
    messages = chat.get("messages") or {}
    if isinstance(messages, list):
        messages = {str(item.get("id")): item for item in messages}
    answer = messages.get(message_id) or {}
    parent = messages.get(str(answer.get("parentId") or "")) or {}
    return {
        "question": str(parent.get("content") or "")[:8000],
        "answer": str(answer.get("content") or "")[:16000],
        "sources": (answer.get("sources") or [])[:30],
        "passages": (answer.get("metadata") or {}).get("sources", [])[:30],
        "runtime": {
            "model": answer.get("model"), "model_id": answer.get("modelId"),
            "prompt_version": "kahle-vinci-current", "retrieval_version": "hybrid-v2",
            "chat_id": chat_id, "message_id": message_id,
        },
        "request_id": str((answer.get("metadata") or {}).get("request_id") or message_id),
    }


@app.post("/portal/feedback/rag", status_code=201)
def portal_report_rag_feedback(
    payload: PortalRagFeedbackRequest, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    rights = PORTAL_GOVERNANCE.allowed_knowledgebases(identity["user_id"], "read")
    try:
        feedback_id = QUALITY_CASES.report_rag(
            user_id=identity["user_id"], reason=payload.reason, comment=payload.comment,
            question=payload.question, answer=payload.answer, sources=payload.sources,
            passages=payload.passages, rights=rights, runtime=payload.runtime, request_id=payload.request_id,
        )
    except QualityCaseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    recipients = _admin_emails() if payload.reason == "suspected_permission_issue" else []
    for recipient in recipients:
        MAINTENANCE.enqueue_notification(
            recipient, "critical_rag_feedback", "KAHLE-Vinci: M?glicher Berechtigungsfehler",
            f"Ein kritischer Wissensfehler wurde gemeldet. Referenz: {feedback_id}", dedupe_key=feedback_id,
        )
    return {"feedback_id": feedback_id, "status": "open"}


SCREENSHOT_INSPECTOR = ScreenshotInspector()


def _feedback_screenshot_dir(feedback_id: str) -> Path:
    safe = PurePosixPath(feedback_id).name
    if not safe or safe != feedback_id:
        raise HTTPException(status_code=422, detail="invalid_feedback_reference")
    return (PORTAL_FILES_ROOT / "feedback-screenshots" / safe).resolve()


@app.post("/portal/feedback/{feedback_id}/screenshot", status_code=201)
async def portal_attach_feedback_screenshot(
    feedback_id: str, file: UploadFile = File(...),
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    """
    Bildanhang zu einer Wissensfehlermeldung.

    Ein Screenshot zeigt dem Admin oft in Sekunden, was eine Beschreibung nur
    umstaendlich erklaert. Der Anhang durchlaeuft dieselbe Kette wie ein
    Dokument: Typpruefung am Inhalt statt an der Endung, Groessengrenze und
    Malwarescan. Nur der Meldende darf anhaengen, nur Admins duerfen abrufen.
    """
    data = await file.read(SCREENSHOT_INSPECTOR.max_bytes + 1)
    try:
        extension, _ = SCREENSHOT_INSPECTOR.inspect(data)
    except IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        SECURE_INGEST.scanner.scan(f"screenshot.{extension}", data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="malware_scan_failed") from exc

    filename = f"screenshot.{extension}"
    try:
        QUALITY_CASES.attach_screenshot(feedback_id, identity["user_id"], filename)
    except QualityCaseError as exc:
        status = 404 if str(exc) == "feedback_not_found" else 403
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    target = _feedback_screenshot_dir(feedback_id)
    target.mkdir(parents=True, exist_ok=True)
    (target / filename).write_bytes(data)
    PORTAL_GOVERNANCE.record_audit(
        identity["user_id"], "feedback_screenshot_attached", "rag_feedback", feedback_id, {},
    )
    return {"feedback_id": feedback_id, "filename": filename}


@app.get("/portal/admin/feedback/{feedback_id}/screenshot")
def portal_admin_feedback_screenshot(
    feedback_id: str, identity: dict[str, Any] = Depends(require_portal_identity),
) -> FileResponse:
    if identity["role"] not in {"admin", "portal_admin"}:
        raise HTTPException(status_code=403, detail="admin_required")
    try:
        filename = QUALITY_CASES.screenshot_of(feedback_id)
    except QualityCaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not filename:
        raise HTTPException(status_code=404, detail="screenshot_not_available")
    path = _feedback_screenshot_dir(feedback_id) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="screenshot_not_available")
    media = "image/png" if filename.endswith(".png") else "image/jpeg"
    return FileResponse(path, media_type=media)


@app.post("/portal/incidents/{incident_id}/comment")
def portal_comment_incident(
    incident_id: str, payload: PortalIncidentCommentRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    del identity
    try:
        QUALITY_CASES.add_incident_comment(incident_id, payload.comment)
    except QualityCaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/portal/admin/quality-cases")
def portal_admin_quality_cases(
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    if identity["role"] not in {"admin", "portal_admin"}:
        raise HTTPException(status_code=403, detail="admin_required")
    return QUALITY_CASES.open_cases()


@app.get("/portal/sources/{version_id}")
def portal_source(
    version_id: str, identity: dict[str, Any] = Depends(require_portal_identity),
) -> FileResponse:
    try:
        record = DOCUMENT_LIFECYCLE.source_record(version_id, identity["user_id"])
    except (LifecycleError, GovernanceError) as exc:
        raise HTTPException(status_code=404, detail="source_not_available") from exc
    version_root = (PORTAL_FILES_ROOT / record["document_id"] / version_id).resolve()
    try:
        version_root.relative_to(PORTAL_FILES_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="source_not_available") from exc
    originals = list(version_root.glob("original.*"))
    if len(originals) != 1 or not originals[0].is_file():
        raise HTTPException(status_code=404, detail="source_not_available")
    inline_extensions = {".pdf", ".txt", ".md"}
    disposition = "inline" if originals[0].suffix.lower() in inline_extensions else "attachment"
    return FileResponse(
        originals[0], filename=record["original_filename"],
        content_disposition_type=disposition,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/portal/cases/{case_id}/review")
def portal_case_review(
    case_id: str, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        review = MARKDOWN_CORRECTION.review(case_id, identity["user_id"])
    except MarkdownCorrectionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"case": asdict(review["case"]), "markdown": review["markdown"],
            "original_url": review["original_url"]}


@app.get("/portal/cases/{case_id}/original")
def portal_case_original(
    case_id: str, identity: dict[str, Any] = Depends(require_portal_identity),
) -> FileResponse:
    try:
        review = MARKDOWN_CORRECTION.review(case_id, identity["user_id"])
    except MarkdownCorrectionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    case = review["case"]; originals = list((PORTAL_FILES_ROOT / case.document_id / case.version_id).glob("original.*"))
    if len(originals) != 1:
        raise HTTPException(status_code=404, detail="original_not_available")
    return FileResponse(originals[0], filename=case.original_filename, content_disposition_type="inline",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@app.post("/portal/cases/{case_id}/revision", status_code=201)
def portal_case_revision(
    case_id: str, payload: PortalMarkdownRevisionRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        revised = MARKDOWN_CORRECTION.revise(
            case_id, identity["user_id"], instruction=payload.instruction,
            replacement_markdown=payload.replacement_markdown, reason=payload.reason,
            confirmed=payload.confirmed,
        )
    except (MarkdownCorrectionError, LifecycleError, requests.RequestException) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    RAG_METADATA.write(revised.version_id)
    return {"case": asdict(revised)}


@app.get("/portal/tasks")
def portal_tasks(identity: dict[str, Any] = Depends(require_portal_identity)) -> dict[str, Any]:
    try:
        tasks = DOCUMENT_LIFECYCLE.tasks_for(identity["user_id"])
    except (LifecycleError, GovernanceError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"tasks": [asdict(task) for task in tasks]}


def _admin_emails() -> list[str]:
    with PORTAL_GOVERNANCE.store.connect() as db:
        return [row["email"] for row in db.execute(
            "SELECT email FROM portal_users WHERE active = 1 AND role IN ('admin','portal_admin')"
        ).fetchall()]


def _notify_case_status(case: Any) -> None:
    recipients: list[str] = []
    if case.status == "pending_manager_approval" and case.manager_user_id:
        recipients.append(PORTAL_GOVERNANCE.identity(case.manager_user_id).email)
    elif case.status == "pending_admin_approval":
        recipients.extend(_admin_emails())
    if not recipients:
        return
    subject = "KAHLE-Vinci: Neue Freigabeaufgabe"
    body = f"F?r den Vorgang '{case.title}' ist eine Entscheidung erforderlich.\n/wissen/?case={case.case_id}"
    for recipient in dict.fromkeys(recipients):
        MAINTENANCE.enqueue_notification(
            recipient, "approval_task", subject, body, dedupe_key=f"{case.case_id}:{case.status}",
        )


def _refresh_global_corpus_version(version_id: str, status: str) -> None:
    with PORTAL_GOVERNANCE.store.connect() as db:
        row = db.execute(
            """SELECT v.version_id,v.document_id,d.title FROM document_versions v
               JOIN canonical_documents d ON d.document_id=v.document_id WHERE v.version_id=?""",
            (version_id,),
        ).fetchone()
        if not row:
            return
        knowledgebase_ids = tuple(item["knowledgebase_id"] for item in db.execute(
            "SELECT knowledgebase_id FROM document_publications WHERE document_id=? AND status!='inactive'",
            (row["document_id"],),
        ).fetchall())
    markdown_path = PORTAL_FILES_ROOT / row["document_id"] / version_id / "rag.md"
    if markdown_path.exists():
        GLOBAL_CORPUS.upsert(CorpusDocument(
            row["document_id"], version_id, row["title"],
            markdown_path.read_text(encoding="utf-8"), knowledgebase_ids, status,
        ))
    else:
        GLOBAL_CORPUS.set_status(version_id, status)


def _notify_system_error(step: str, diagnostic: dict[str, Any]) -> str:
    incident_id = QUALITY_CASES.system_incident(step, diagnostic)
    for recipient in _admin_emails():
        MAINTENANCE.enqueue_notification(
            recipient, "system_error", "KAHLE-Vinci: Systemfehler",
            f"Ein Systemfehler ist aufgetreten. Referenz: {incident_id}",
            dedupe_key=incident_id,
        )
    return incident_id


@app.post("/portal/cases/{case_id}/action")
def portal_case_action(
    case_id: str, payload: PortalCaseActionRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        if payload.action == "replace":
            if not payload.target_document_id:
                raise LifecycleError("replacement_target_required")
            before = DOCUMENT_LIFECYCLE.submission(case_id)
            source_dir = (PORTAL_FILES_ROOT / before.document_id / before.version_id).resolve()
            target_dir = (PORTAL_FILES_ROOT / payload.target_document_id / before.version_id).resolve()
            source_dir.relative_to(PORTAL_FILES_ROOT.resolve())
            target_dir.relative_to(PORTAL_FILES_ROOT.resolve())
            if not source_dir.is_dir() or target_dir.exists():
                raise LifecycleError("replacement_storage_not_ready")
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            source_dir.rename(target_dir)
            bound_complete = False
            try:
                bound = DOCUMENT_LIFECYCLE.bind_replacement(
                    case_id=case_id, target_document_id=payload.target_document_id,
                    actor_user_id=identity["user_id"],
                )
                bound_complete = True
                RAG_METADATA.write(bound.version_id, target_dir / "rag.md")
                with PORTAL_GOVERNANCE.store.connect() as db:
                    kb_ids = tuple(row["knowledgebase_id"] for row in db.execute(
                        "SELECT knowledgebase_id FROM document_publications WHERE document_id=?",
                        (bound.document_id,),
                    ).fetchall())
                GLOBAL_CORPUS.upsert(CorpusDocument(
                    bound.document_id, bound.version_id, bound.title,
                    (target_dir / "rag.md").read_text(encoding="utf-8"), kb_ids, "pending",
                ))
                try:
                    source_dir.parent.rmdir()
                except OSError:
                    pass
            except Exception:
                if not bound_complete and target_dir.exists() and not source_dir.exists():
                    source_dir.parent.mkdir(parents=True, exist_ok=True)
                    target_dir.rename(source_dir)
                raise
        case = DOCUMENT_LIFECYCLE.choose_action(
            case_id=case_id, actor_user_id=identity["user_id"], action=payload.action,
        )
    except LifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        incident_id = _notify_system_error("replacement_binding", {"error_type": type(exc).__name__})
        raise HTTPException(status_code=500, detail=f"system_error:{incident_id}") from exc
    if case.status == "withdrawn":
        GLOBAL_CORPUS.set_status(case.version_id, "withdrawn")
    _notify_case_status(case)
    return {"case": asdict(case)}


@app.post("/portal/cases/{case_id}/decision")
def portal_case_decision(
    case_id: str, payload: PortalCaseDecisionRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        case = DOCUMENT_LIFECYCLE.decide(
            case_id=case_id, actor_user_id=identity["user_id"],
            decision=payload.decision, reason=payload.reason,
        )
        if case.status == "ready_to_activate" and case.requested_action == "publish_existing":
            case, target_version_id, previous_publication_status = DOCUMENT_LIFECYCLE.publish_existing(case_id=case_id)
            RAG_METADATA.write(target_version_id)
            indexing = _trigger_hybrid_reindex()
            if not indexing.get("ok"):
                case = DOCUMENT_LIFECYCLE.rollback_existing_publication(
                    case_id=case_id, previous_status=previous_publication_status,
                    reason=str(indexing.get("error") or "hybrid_reindex_failed"),
                )
                _trigger_hybrid_reindex()
                _refresh_global_corpus_version(case.version_id, "pending")
                _refresh_global_corpus_version(target_version_id, "active")
                raise HTTPException(status_code=503, detail="publication_index_failed_previous_scope_restored")
            _refresh_global_corpus_version(case.version_id, "withdrawn_duplicate")
            _refresh_global_corpus_version(target_version_id, "active")
        elif case.status == "ready_to_activate":
            previous_version_id = DOCUMENT_LIFECYCLE.active_version(case.document_id)
            case = DOCUMENT_LIFECYCLE.activate(case_id=case_id)
            RAG_METADATA.write(case.version_id)
            indexing = _trigger_hybrid_reindex()
            if not indexing.get("ok"):
                case = DOCUMENT_LIFECYCLE.rollback_activation(
                    case_id=case_id, previous_version_id=previous_version_id,
                    reason=str(indexing.get("error") or "hybrid_reindex_failed"),
                )
                # If the index switch completed but its response was lost, restore the old generation too.
                _trigger_hybrid_reindex()
                _refresh_global_corpus_version(case.version_id, "pending")
                if previous_version_id:
                    _refresh_global_corpus_version(previous_version_id, "active")
                raise HTTPException(status_code=503, detail="activation_index_failed_previous_version_restored")
            _refresh_global_corpus_version(case.version_id, "active")
            if previous_version_id and previous_version_id != case.version_id:
                _refresh_global_corpus_version(previous_version_id, "superseded")
        elif case.status == "rejected":
            GLOBAL_CORPUS.set_status(case.version_id, "rejected")
    except HTTPException:
        raise
    except (LifecycleError, GovernanceError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _notify_case_status(case)
    return {"case": asdict(case)}


@app.get("/portal/auth/step-up/start")
def portal_step_up_start(
    return_to: str = "/wissen/",
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    if STEP_UP_AUTHORITY is None:
        raise HTTPException(status_code=503, detail="microsoft_step_up_not_configured")
    try:
        started = STEP_UP_AUTHORITY.begin(
            user_id=identity["user_id"],
            email=identity["email"],
            return_to=return_to,
        )
    except StepUpError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    PORTAL_GOVERNANCE.record_audit(
        identity["user_id"], "step_up_started", "user", identity["user_id"],
        {"return_to": return_to},
    )
    return {
        "authorization_url": started.authorization_url,
        "expires_in": started.expires_in,
    }


@app.get("/portal/auth/step-up/local-confirm", response_class=HTMLResponse)
def portal_step_up_local_confirm(
    state: str, code: str, email: str = "",
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> HTMLResponse:
    """
    Bestaetigungsseite der lokalen Abnahme, an Microsofts Stelle.

    Existiert nur, solange der lokale Adapter aktiv ist. Der Schritt bleibt
    bewusst ein eigener Klick, damit lokal derselbe Ablauf durchlaufen wird wie
    produktiv mit der zweiten Microsoft-Anmeldung.
    """
    if not isinstance(getattr(STEP_UP_AUTHORITY, "oidc", None), LocalStepUpAdapter):
        raise HTTPException(status_code=404, detail="not_found")
    callback = (
        "/wissen/api/portal/auth/step-up/callback"
        f"?state={quote(state, safe='')}&code={quote(code, safe='')}"
    )
    return HTMLResponse(f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<title>Bestätigung erforderlich</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:34rem;margin:12vh auto;padding:0 1.5rem;color:#171a1d}}
 h1{{font-size:1.3rem}} p{{line-height:1.55;color:#414a52}}
 .warn{{background:#fff2dd;border-left:3px solid #d68a1c;padding:.9rem 1rem;color:#7e500e;font-size:.9rem}}
 a.btn{{display:inline-block;margin-top:1.4rem;background:#006bb6;color:#fff;
   padding:.7rem 1.3rem;border-radius:5px;text-decoration:none;font-weight:600}}
 a.btn:focus-visible{{outline:3px solid #006bb6;outline-offset:2px}}
</style></head><body>
<h1>Kritische Aktion bestätigen</h1>
<p>Produktiv verlangt dieser Schritt eine erneute Anmeldung bei Microsoft.
In dieser lokalen Abnahmeumgebung ist kein Microsoft-Konto angebunden.</p>
<p class="warn">Lokaler Ersatz für die zweite Anmeldung. Deine Rolle und deine
Rechte werden weiterhin vollständig serverseitig geprüft.</p>
<p>Angemeldet als <strong>{escape(identity["email"])}</strong>.</p>
<a class="btn" href="{escape(callback, quote=True)}">Bestätigen und fortfahren</a>
</body></html>""")


@app.get("/portal/auth/step-up/callback")
def portal_step_up_callback(
    state: str,
    code: str,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> RedirectResponse:
    if STEP_UP_AUTHORITY is None:
        raise HTTPException(status_code=503, detail="microsoft_step_up_not_configured")
    try:
        proof, return_to = STEP_UP_AUTHORITY.complete(
            current_user_id=identity["user_id"], state=state, code=code
        )
    except StepUpError as exc:
        PORTAL_GOVERNANCE.record_audit(
            identity["user_id"], "step_up_failed", "user", identity["user_id"],
            {"reason": str(exc)},
        )
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    PORTAL_GOVERNANCE.record_audit(
        identity["user_id"], "step_up_completed", "user", identity["user_id"],
        {"return_to": return_to},
    )
    response = RedirectResponse(return_to, status_code=303)
    response.set_cookie(
        key=StepUpAuthority.COOKIE_NAME,
        value=proof,
        max_age=STEP_UP_AUTHORITY.proof_ttl_seconds,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response

@app.get("/portal/documents/{document_id}/authority")
def portal_document_authority(
    document_id: str, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        return DOCUMENT_AUTHORITY.view(identity["user_id"], document_id)
    except AuthorityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/portal/documents/{document_id}/authority")
def portal_update_document_authority(
    document_id: str, payload: PortalAuthorityRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        result = DOCUMENT_AUTHORITY.update(
            identity["user_id"], document_id, payload.authority_type, payload.scope, payload.reason,
        )
        with PORTAL_GOVERNANCE.store.connect() as db:
            version = db.execute(
                "SELECT version_id FROM document_versions WHERE document_id=? ORDER BY created_at DESC LIMIT 1",
                (document_id,),
            ).fetchone()
        if version:
            RAG_METADATA.write(version["version_id"])
            indexing = _trigger_hybrid_reindex()
            if not indexing.get("ok"):
                incident_id = _notify_system_error(
                    "authority_reindex", {"document_id": document_id, "error": indexing.get("error")}
                )
                raise HTTPException(status_code=503, detail=f"authority_reindex_failed:{incident_id}")
        return {**result, "reindex": {"ok": True}}
    except AuthorityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/portal/documents/{document_id}/authority-relations", status_code=201)
def portal_create_authority_relation(
    document_id: str, payload: PortalAuthorityRelationRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        relation_id = DOCUMENT_AUTHORITY.relate(
            identity["user_id"], document_id, payload.target_document_id,
            payload.relation_type, payload.condition_text, payload.reason,
        )
        return {"relation_id": relation_id}
    except AuthorityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/portal/ownership-tasks")
def portal_ownership_tasks(
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    return {"tasks": OWNERSHIP.tasks_for(identity["user_id"])}


@app.get("/portal/owner-candidates")
def portal_owner_candidates(
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    return {
        "can_propose_other": OWNERSHIP.may_propose_other(identity["user_id"]),
        "users": OWNERSHIP.active_candidates(identity["user_id"]),
    }


@app.get("/portal/admin/users/{target_user_id}/owner-proposal-permission")
def portal_admin_owner_permission(
    target_user_id: str, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    if identity["role"] not in {"admin", "portal_admin"}:
        raise HTTPException(status_code=403, detail="admin_required")
    return {"allowed": OWNERSHIP.may_propose_other(target_user_id)}


@app.put("/portal/admin/users/{target_user_id}/owner-proposal-permission")
def portal_admin_set_owner_permission(
    target_user_id: str, payload: PortalOwnerPermissionRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        OWNERSHIP.set_proposal_permission(identity["user_id"], target_user_id, payload.allowed)
    except OwnershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"allowed": payload.allowed}


@app.post("/portal/ownership-tasks/{task_id}/proposal")
def portal_propose_owner(
    task_id: str, payload: PortalOwnershipProposalRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        OWNERSHIP.propose(task_id, identity["user_id"], payload.proposed_owner_user_id, payload.reason)
    except OwnershipError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "pending_owner_confirmation"}


@app.post("/portal/ownership-tasks/{task_id}/confirmation")
def portal_confirm_owner(
    task_id: str, payload: PortalOwnershipConfirmationRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        status = OWNERSHIP.confirm(task_id, identity["user_id"], payload.accept, payload.reason)
        if status == "completed" and payload.accept:
            with PORTAL_GOVERNANCE.store.connect() as db:
                version = db.execute(
                    """SELECT v.version_id FROM owner_reassignment_tasks t
                       JOIN canonical_documents d ON d.document_id=t.document_id
                       JOIN document_versions v ON v.document_id=d.document_id
                       WHERE t.task_id=? ORDER BY v.created_at DESC LIMIT 1""", (task_id,),
                ).fetchone()
            if version:
                RAG_METADATA.write(version["version_id"])
                indexing = _trigger_hybrid_reindex()
                if not indexing.get("ok"):
                    incident_id = _notify_system_error(
                        "owner_reindex", {"task_id": task_id, "error": indexing.get("error")}
                    )
                    raise HTTPException(status_code=503, detail=f"owner_reindex_failed:{incident_id}")
    except OwnershipError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": status}


@app.post("/portal/document-changes/renewal", status_code=201)
def portal_request_renewal(
    payload: PortalRenewalRequest, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try: request_id=DOCUMENT_CHANGES.request_renewal(payload.document_id,identity["user_id"],payload.reason,payload.confirmed)
    except DocumentChangeError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
    return {"request_id":request_id}


@app.post("/portal/document-changes/confidentiality", status_code=201)
def portal_request_confidentiality(
    payload: PortalConfidentialityRequest, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try: request_id=DOCUMENT_CHANGES.request_confidentiality(payload.document_id,identity["user_id"],payload.desired,payload.reason)
    except DocumentChangeError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
    return {"request_id":request_id}


@app.get("/portal/document-changes")
def portal_document_changes(identity: dict[str, Any] = Depends(require_portal_identity)) -> dict[str, Any]:
    return {"changes":DOCUMENT_CHANGES.pending_for(identity["user_id"])}


@app.post("/portal/document-changes/{request_id}/decision")
def portal_decide_document_change(
    request_id: str,payload: PortalDocumentChangeDecisionRequest,identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try: status=DOCUMENT_CHANGES.decide(request_id,identity["user_id"],payload.approve,payload.reason)
    except DocumentChangeError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
    if status=="approved": _trigger_hybrid_reindex()
    return {"status":status}


@app.post("/portal/removal-requests", status_code=201)
def portal_request_removal(
    payload: PortalRemovalRequest, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        request_id = MAINTENANCE.request_removal(payload.document_id, identity["user_id"], payload.kind, payload.reason)
    except MaintenanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if identity["role"] in {"admin", "portal_admin"}:
        indexing = _trigger_hybrid_reindex()
        if not indexing.get("ok"): raise HTTPException(status_code=503, detail="removal_reindex_failed")
    return {"request_id": request_id}


@app.get("/portal/admin/removals")
def portal_admin_removals(identity: dict[str, Any] = Depends(require_portal_identity)) -> dict[str, Any]:
    if identity["role"] not in {"admin", "portal_admin"}: raise HTTPException(status_code=403, detail="admin_required")
    return MAINTENANCE.list_removals()


@app.post("/portal/admin/removal-requests/{request_id}/decision")
def portal_admin_decide_removal(
    request_id: str, payload: PortalRemovalDecisionRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try: MAINTENANCE.decide_removal(request_id, identity["user_id"], payload.approve, payload.reason)
    except MaintenanceError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
    if payload.approve:
        indexing = _trigger_hybrid_reindex()
        if not indexing.get("ok"): raise HTTPException(status_code=503, detail="removal_reindex_failed")
    return {"ok": True}


@app.post("/portal/admin/trash/{document_id}/restore")
def portal_admin_restore_trash(
    document_id: str, payload: PortalRestoreRequest, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try: MAINTENANCE.restore_from_trash(document_id, identity["user_id"], payload.reason)
    except MaintenanceError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
    indexing = _trigger_hybrid_reindex()
    if not indexing.get("ok"): raise HTTPException(status_code=503, detail="restore_reindex_failed")
    return {"ok": True}


@app.put("/portal/admin/trash/{document_id}/legal-hold")
def portal_admin_legal_hold(
    document_id: str, payload: PortalLegalHoldRequest, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try: MAINTENANCE.set_legal_hold(document_id, identity["user_id"], payload.enabled, payload.reason, payload.review_at)
    except MaintenanceError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/portal/admin/dashboard")
def portal_admin_dashboard(
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    if identity["role"] not in {"admin", "portal_admin"}:
        raise HTTPException(status_code=403, detail="admin_required")
    result = QUALITY_DASHBOARD.snapshot()
    try:
        response = requests.get(f"{KB_SYNC_URL}/health", timeout=10)
        result["index"] = response.json() if response.status_code == 200 else {"ok": False}
    except requests.RequestException:
        result["index"] = {"ok": False, "error": "unavailable"}
    return result


@app.post("/portal/admin/migration/inventory")
def portal_admin_migration_inventory(
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    if identity["role"] not in {"admin", "portal_admin"}:
        raise HTTPException(status_code=403, detail="admin_required")
    return {"items": [asdict(item) for item in LEGACY_MIGRATION.inventory(KB_ROOT)]}


@app.put("/portal/admin/migration/metadata")
def portal_admin_migration_metadata(
    payload: PortalMigrationMetadataRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    try:
        LEGACY_MIGRATION.resolve_metadata(
            payload.path, identity["user_id"], owner_email=payload.owner_email,
            confidentiality=payload.confidentiality, authority_type=payload.authority_type,
            authority_level=payload.authority_level, scope=payload.scope,
        )
    except (GovernanceError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "metadata_resolved"}


@app.post("/portal/admin/migration/stage")
def portal_admin_migration_stage(
    payload: PortalMigrationStageRequest, request: Request,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    if identity["role"] != "portal_admin":
        raise HTTPException(status_code=403, detail="portal_admin_required")
    require_fresh_step_up(request, identity)
    try:
        case_id = LEGACY_MIGRATION.stage(KB_ROOT, payload.path, identity["user_id"])
    except (ValueError, LifecycleError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"case_id": case_id, "status": "staged"}


@app.get("/portal/admin/audit")
def portal_admin_audit(
    limit: int = 250, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    if identity["role"] not in {"admin", "portal_admin"}:
        raise HTTPException(status_code=403, detail="admin_required")
    return {"entries": [asdict(item) for item in AUDIT_EXPORTER.entries(limit)]}


@app.get("/portal/admin/audit/export.{format}")
def portal_admin_audit_export(
    format: str, identity: dict[str, Any] = Depends(require_portal_identity),
) -> FastAPIResponse:
    if identity["role"] not in {"admin", "portal_admin"}:
        raise HTTPException(status_code=403, detail="admin_required")
    if format == "csv":
        return FastAPIResponse(AUDIT_EXPORTER.csv_bytes(), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="kahle-vinci-audit.csv"'})
    if format == "pdf":
        return FastAPIResponse(AUDIT_EXPORTER.pdf_bytes(), media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="kahle-vinci-audit.pdf"'})
    raise HTTPException(status_code=404, detail="unknown_audit_format")


def _sync_openwebui_user_directory(request: Request) -> None:
    if DEV_AUTH_BYPASS:
        return
    headers: dict[str, str] = {}
    if request.headers.get("Authorization"):
        headers["Authorization"] = request.headers["Authorization"]
    if request.headers.get("Cookie"):
        headers["Cookie"] = request.headers["Cookie"]
    try:
        response = requests.get(f"{OPENWEBUI_URL}/api/v1/users/", headers=headers, timeout=20)
        response.raise_for_status()
        payload = response.json()
        users = payload.get("users", payload) if isinstance(payload, dict) else payload
        if not isinstance(users, list):
            raise ValueError("invalid_openwebui_user_directory")
        for item in users:
            user_id = str(item.get("id") or "").strip()
            email = str(item.get("email") or "").strip()
            email_domain = email.rsplit("@", 1)[-1].casefold() if "@" in email else ""
            if not user_id or not email or email_domain not in PORTAL_ALLOWED_EMAIL_DOMAINS:
                continue
            PORTAL_GOVERNANCE.sync_identity(
                user_id=user_id, email=email,
                display_name=str(item.get("name") or item.get("display_name") or email).strip(),
                active=True, bootstrap_portal_admin=False,
            )
    except Exception as exc:
        incident_id = _notify_system_error(
            "openwebui_user_directory_sync", {"error_type": type(exc).__name__}
        )
        raise HTTPException(status_code=503, detail=f"user_directory_sync_failed:{incident_id}") from exc


@app.get("/portal/admin/users")
def portal_admin_users(
    request: Request, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    if str(identity.get("openwebui_role") or "").lower() == "admin":
        _sync_openwebui_user_directory(request)
    users = _portal_call(lambda: PORTAL_GOVERNANCE.list_identities(identity["user_id"]))
    return {"users": serialize_governance(users)}


@app.patch("/portal/admin/users/{target_user_id}/role")
def portal_admin_set_role(
    target_user_id: str,
    payload: PortalRoleRequest,
    request: Request,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    require_fresh_step_up(request, identity)
    user = _portal_call(
        lambda: PORTAL_GOVERNANCE.set_role(identity["user_id"], target_user_id, payload.role)
    )
    return {"user": serialize_governance(user)}


@app.patch("/portal/admin/users/{target_user_id}/activation")
def portal_admin_set_activation(
    target_user_id: str,
    payload: PortalActivationRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    user = _portal_call(
        lambda: PORTAL_GOVERNANCE.set_active(identity["user_id"], target_user_id, payload.active)
    )
    reassignment_tasks = [] if payload.active else OWNERSHIP.create_for_deactivated_owner(
        target_user_id, identity["user_id"]
    )
    return {"user": serialize_governance(user), "owner_reassignment_task_ids": reassignment_tasks}


@app.patch("/portal/admin/users/{target_user_id}/manager")
def portal_admin_assign_manager(
    target_user_id: str,
    payload: PortalManagerRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    user = _portal_call(
        lambda: PORTAL_GOVERNANCE.assign_manager(
            identity["user_id"], target_user_id, payload.manager_user_id
        )
    )
    return {"user": serialize_governance(user)}


@app.get("/portal/admin/absences")
def portal_admin_absences(identity: dict[str, Any] = Depends(require_portal_identity)) -> dict[str, Any]:
    return {"absences": _portal_call(lambda: PORTAL_GOVERNANCE.list_absences(identity["user_id"]))}


@app.put("/portal/admin/absences")
def portal_admin_set_absence(
    payload: PortalAbsenceRequest, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    _portal_call(lambda: PORTAL_GOVERNANCE.set_absence(
        identity["user_id"], payload.manager_user_id, payload.absent_from,
        payload.absent_until, payload.reason,
    ))
    return {"ok": True}


@app.get("/portal/admin/delegations")
def portal_admin_delegations(identity: dict[str, Any] = Depends(require_portal_identity)) -> dict[str, Any]:
    return {"delegations": _portal_call(lambda: PORTAL_GOVERNANCE.list_delegations(identity["user_id"]))}


@app.put("/portal/admin/delegations")
def portal_admin_set_delegation(
    payload: PortalDelegationRequest, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    _portal_call(lambda: PORTAL_GOVERNANCE.assign_delegate(identity["user_id"],payload.manager_user_id,payload.delegate_user_id,valid_from=payload.valid_from,valid_until=payload.valid_until))
    return {"ok":True}


@app.delete("/portal/admin/delegations")
def portal_admin_remove_delegation(
    manager_user_id: str, delegate_user_id: str, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    _portal_call(lambda: PORTAL_GOVERNANCE.remove_delegate(identity["user_id"],manager_user_id,delegate_user_id))
    return {"ok":True}


@app.get("/portal/admin/users/{target_user_id}/knowledgebase-access")
def portal_admin_user_access(
    target_user_id: str, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    access = _portal_call(
        lambda: PORTAL_GOVERNANCE.access_for_user(identity["user_id"], target_user_id)
    )
    return {"access": access}


@app.put("/portal/admin/users/{target_user_id}/knowledgebase-access")
def portal_admin_grant_access(
    target_user_id: str,
    payload: PortalAccessRequest,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    _portal_call(
        lambda: PORTAL_GOVERNANCE.grant_access(
            identity["user_id"],
            target_user_id,
            payload.knowledgebase_id,
            can_read=payload.can_read,
            can_upload=payload.can_upload,
        )
    )
    return {"ok": True}


@app.get("/portal/admin/knowledgebase-changes")
def portal_admin_list_knowledgebase_changes(
    status: str | None = None, identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    changes = _portal_call(lambda: PORTAL_GOVERNANCE.list_change_requests(identity["user_id"], status))
    return {"changes": serialize_governance(changes)}


@app.post("/portal/admin/knowledgebase-changes", status_code=201)
def portal_admin_request_knowledgebase_change(
    payload: PortalKnowledgebaseChangeRequest,
    request: Request,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    if identity["role"] == "portal_admin":
        require_fresh_step_up(request, identity)
    change = _portal_call(
        lambda: PORTAL_GOVERNANCE.request_knowledgebase_change(
            identity["user_id"],
            payload.kind,
            knowledgebase_id=payload.knowledgebase_id,
            payload=payload.payload,
        )
    )
    return {"change": serialize_governance(change)}

@app.post("/portal/admin/knowledgebase-changes/{request_id}/decision")
def portal_admin_decide_knowledgebase_change(
    request_id: str,
    payload: PortalKnowledgebaseDecisionRequest,
    request: Request,
    identity: dict[str, Any] = Depends(require_portal_identity),
) -> dict[str, Any]:
    require_fresh_step_up(request, identity)
    change = _portal_call(
        lambda: PORTAL_GOVERNANCE.decide_knowledgebase_change(
            identity["user_id"],
            request_id,
            approve=payload.approve,
            reason=payload.reason,
        )
    )
    return {"change": serialize_governance(change)}

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

