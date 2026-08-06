from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from .document_lifecycle import Analysis, DocumentLifecycle
    from .global_analysis import CorpusDocument, GlobalCorpus, GlobalDocumentAnalyzer
    from .portal_governance import PortalGovernance
    from .secure_ingest import PromptInjectionInspector, QuarantineStorage
except ImportError:  # pragma: no cover
    from document_lifecycle import Analysis, DocumentLifecycle
    from global_analysis import CorpusDocument, GlobalCorpus, GlobalDocumentAnalyzer
    from portal_governance import PortalGovernance
    from secure_ingest import PromptInjectionInspector, QuarantineStorage


def parse_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    if not markdown.startswith("---"):
        return {}, markdown
    end = markdown.find("\n---", 3)
    if end < 0:
        return {}, markdown
    metadata: dict[str, str] = {}
    for line in markdown[3:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip().strip('"\'')
    return metadata, markdown[end + 4:].lstrip("\r\n")


@dataclass(frozen=True)
class MigrationItem:
    path: str
    knowledgebase_slug: str
    document_id: str
    version_id: str
    status: str
    missing: tuple[str, ...]
    prompt_injection_risk: str


class LegacyMigrationService:
    REQUIRED = ("owner", "confidentiality")

    def __init__(self, governance: PortalGovernance, lifecycle: DocumentLifecycle,
                 analyzer: GlobalDocumentAnalyzer, corpus: GlobalCorpus, storage: QuarantineStorage):
        self.governance, self.lifecycle = governance, lifecycle
        self.analyzer, self.corpus, self.storage = analyzer, corpus, storage
        self.injection = PromptInjectionInspector()
        self._initialize()

    def _initialize(self) -> None:
        with self.governance.store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS migration_inventory (
                path TEXT PRIMARY KEY, knowledgebase_slug TEXT NOT NULL, document_id TEXT NOT NULL,
                version_id TEXT NOT NULL, status TEXT NOT NULL, missing_json TEXT NOT NULL,
                prompt_injection_risk TEXT NOT NULL, case_id TEXT, updated_at TEXT NOT NULL,
                metadata_override_json TEXT
            )""")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(migration_inventory)")}
            if "metadata_override_json" not in columns:
                db.execute("ALTER TABLE migration_inventory ADD COLUMN metadata_override_json TEXT")

    def inventory(self, root: Path) -> list[MigrationItem]:
        root = root.resolve(); items: list[MigrationItem] = []
        seen_hashes: dict[str, str] = {}
        for path in sorted(root.glob("*/*.md")):
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            relative = path.relative_to(root).as_posix()
            markdown = path.read_text(encoding="utf-8-sig", errors="replace")
            metadata, body = parse_frontmatter(markdown)
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"kahle-migration:{relative}"))
            version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"kahle-migration:{relative}:{digest}"))
            missing = tuple(field for field in self.REQUIRED if not metadata.get(field))
            risk = self.injection.inspect(body).risk
            status = "quarantine" if risk in {"high", "critical"} or digest in seen_hashes else (
                "ready_to_stage" if not missing else "metadata_required"
            )
            seen_hashes[digest] = relative
            item = MigrationItem(relative, path.parent.name, document_id, version_id, status, missing, risk)
            items.append(item)
            with self.governance.store.connect() as db:
                db.execute("""INSERT INTO migration_inventory
                    (path,knowledgebase_slug,document_id,version_id,status,missing_json,prompt_injection_risk,case_id,updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, datetime('now'))
                    ON CONFLICT(path) DO UPDATE SET document_id=excluded.document_id,
                    version_id=excluded.version_id, status=excluded.status, missing_json=excluded.missing_json,
                    prompt_injection_risk=excluded.prompt_injection_risk, updated_at=excluded.updated_at""",
                    (relative, item.knowledgebase_slug, document_id, version_id, status,
                     json.dumps(missing), risk))
        return items

    def resolve_metadata(self, relative_path: str, actor_user_id: str, *, owner_email: str,
                         confidentiality: str, authority_type: str,
                         authority_level: int, scope: dict[str, Any]) -> None:
        actor = self.governance.identity(actor_user_id)
        if actor.role not in {"admin", "portal_admin"}:
            raise ValueError("admin_required")
        owners = self.governance.list_identities(actor_user_id)
        owner = next((item for item in owners if item.active and item.email.casefold() == owner_email.casefold()), None)
        if not owner or confidentiality not in {"internal", "restricted", "confidential"}:
            raise ValueError("valid_owner_and_confidentiality_required")
        if authority_level not in range(1, 7) or not authority_type.strip():
            raise ValueError("valid_authority_required")
        override = {"owner": owner.email, "confidentiality": confidentiality,
                    "authority_type": authority_type.strip(), "authority_level": authority_level,
                    "scope": scope}
        with self.governance.store.connect() as db:
            row = db.execute("SELECT status,prompt_injection_risk FROM migration_inventory WHERE path=?", (relative_path,)).fetchone()
            if not row:
                raise ValueError("migration_item_unknown")
            status = "quarantine" if row["prompt_injection_risk"] in {"high", "critical"} else "ready_to_stage"
            db.execute("UPDATE migration_inventory SET metadata_override_json=?, missing_json='[]', status=?, updated_at=datetime('now') WHERE path=?",
                       (json.dumps(override, ensure_ascii=False, sort_keys=True), status, relative_path))

    def stage(self, root: Path, relative_path: str, portal_admin_user_id: str) -> str:
        root = root.resolve(); source = (root / relative_path).resolve(); source.relative_to(root)
        with self.governance.store.connect() as db:
            row = db.execute("SELECT * FROM migration_inventory WHERE path = ?", (relative_path,)).fetchone()
        if not row or row["status"] != "ready_to_stage":
            raise ValueError("migration_item_not_ready")
        markdown = source.read_text(encoding="utf-8-sig", errors="replace")
        metadata, body = parse_frontmatter(markdown)
        override = json.loads(row["metadata_override_json"] or "{}")
        metadata = {**metadata, **override}
        owner = next((user for user in self.governance.list_identities(portal_admin_user_id)
                      if user.email.casefold() == metadata["owner"].casefold()), None)
        if not owner:
            raise ValueError("migration_owner_unknown")
        kb = next((item for item in self.governance.list_knowledgebases(portal_admin_user_id, "upload")
                   if item.slug == row["knowledgebase_slug"]), None)
        if not kb:
            raise ValueError("migration_knowledgebase_unknown")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        case_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"case:{row['version_id']}"))
        submission = self.lifecycle.submit(
            uploaded_by_user_id=portal_admin_user_id, owner_user_id=owner.user_id,
            target_knowledgebase_id=kb.knowledgebase_id, title=metadata.get("title") or source.stem,
            original_filename=source.name, original_file_id=f"legacy://{relative_path}", original_sha256=digest,
            valid_workdays=60, confidentiality=metadata["confidentiality"],
            document_id=row["document_id"], version_id=row["version_id"], case_id=case_id,
        )
        if override:
            with self.governance.store.connect() as db:
                db.execute("UPDATE document_metadata SET authority_type=?,authority_level=?,scope_json=? WHERE document_id=?",
                           (override["authority_type"], override["authority_level"],
                            json.dumps(override.get("scope", {}), ensure_ascii=False, sort_keys=True), submission.document_id))
        original = self.storage.store(submission.document_id, submission.version_id, "md", source.read_bytes())
        self.storage.store_markdown(original, body)
        analysis = self.analyzer.analyze(version_id=submission.version_id, title=submission.title, markdown=body)
        case = self.lifecycle.record_analysis(
            case_id=case_id, normalized_sha256=analysis.normalized_sha256,
            markdown_sha256=hashlib.sha256(body.encode()).hexdigest(),
            analysis=Analysis(
                exact_duplicate_document_id=analysis.exact_document_id,
                cross_kb_matches=tuple(match.document_id for match in analysis.matches
                                       if kb.knowledgebase_id not in match.knowledgebase_ids),
                contradiction_document_ids=analysis.contradiction_document_ids,
                prompt_injection_risk=row["prompt_injection_risk"],
            ), actor_user_id="migration",
        )
        self.corpus.upsert(CorpusDocument(case.document_id, case.version_id, case.title, body,
                                          (kb.knowledgebase_id,), "pending"))
        with self.governance.store.connect() as db:
            db.execute("UPDATE migration_inventory SET status = 'staged', case_id = ? WHERE path = ?",
                       (case_id, relative_path))
        return case_id
