from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Callable

try:
    from .document_lifecycle import Analysis, DocumentLifecycle, add_workdays
    from .global_analysis import CorpusDocument, GlobalCorpus, GlobalDocumentAnalyzer
    from .portal_governance import PortalGovernance
    from .secure_ingest import ConversionQualityInspector, PromptInjectionInspector, QuarantineStorage, SecureIngestPipeline
except ImportError:  # pragma: no cover
    from document_lifecycle import Analysis, DocumentLifecycle, add_workdays
    from global_analysis import CorpusDocument, GlobalCorpus, GlobalDocumentAnalyzer
    from portal_governance import PortalGovernance
    from secure_ingest import ConversionQualityInspector, PromptInjectionInspector, QuarantineStorage, SecureIngestPipeline


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
    original_path: str
    markdown_path: str | None
    knowledgebase_slug: str
    document_id: str
    version_id: str
    status: str
    missing: tuple[str, ...]
    prompt_injection_risk: str
    conversion_quality: str
    conversion_issues: tuple[str, ...]
    transition_deadline: str
    exclusion_reason: str | None = None
    excluded_by: str | None = None
    excluded_at: str | None = None


class LegacyMigrationService:
    REQUIRED = ("owner", "confidentiality", "authority_type", "authority_level", "scope")
    SOURCE_EXTENSIONS = {".md", ".txt", ".pdf", ".docx", ".xlsx", ".pptx"}

    def __init__(self, governance: PortalGovernance, lifecycle: DocumentLifecycle,
                 analyzer: GlobalDocumentAnalyzer, corpus: GlobalCorpus, storage: QuarantineStorage,
                 ingest: SecureIngestPipeline | None = None, today: Callable[[], date] = date.today,
                 restricted_term_matcher: Callable[[str], tuple[str, ...]] | None = None):
        self.governance, self.lifecycle = governance, lifecycle
        self.analyzer, self.corpus, self.storage = analyzer, corpus, storage
        self.injection = PromptInjectionInspector()
        self.quality = ConversionQualityInspector()
        self.ingest = ingest
        self.today = today
        self.restricted_term_matcher = restricted_term_matcher or (lambda _text: ())
        self._initialize()
        self._resume_staged_workflows()

    def _initialize(self) -> None:
        with self.governance.store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS migration_inventory (
                path TEXT PRIMARY KEY, knowledgebase_slug TEXT NOT NULL, document_id TEXT NOT NULL,
                version_id TEXT NOT NULL, status TEXT NOT NULL, missing_json TEXT NOT NULL,
                prompt_injection_risk TEXT NOT NULL, case_id TEXT, updated_at TEXT NOT NULL,
                metadata_override_json TEXT, original_path TEXT, markdown_path TEXT,
                conversion_quality TEXT NOT NULL DEFAULT 'unknown', conversion_issues_json TEXT NOT NULL DEFAULT '[]',
                transition_deadline TEXT, transition_status TEXT NOT NULL DEFAULT 'pending'
            )""")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(migration_inventory)")}
            if "metadata_override_json" not in columns:
                db.execute("ALTER TABLE migration_inventory ADD COLUMN metadata_override_json TEXT")
            additions = {
                "original_path": "TEXT", "markdown_path": "TEXT",
                "conversion_quality": "TEXT NOT NULL DEFAULT 'unknown'",
                "conversion_issues_json": "TEXT NOT NULL DEFAULT '[]'",
                "transition_deadline": "TEXT", "transition_status": "TEXT NOT NULL DEFAULT 'pending'",
                "exclusion_reason": "TEXT", "excluded_by": "TEXT", "excluded_at": "TEXT",
                "previous_status": "TEXT",
            }
            for name, declaration in additions.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE migration_inventory ADD COLUMN {name} {declaration}")
            db.execute("""CREATE TABLE IF NOT EXISTS migration_tasks (
                task_id TEXT PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open', details_json TEXT NOT NULL,
                created_at TEXT NOT NULL, resolved_at TEXT,
                UNIQUE(path, kind)
            )""")

    def _resume_staged_workflows(self) -> None:
        """Advance legacy cases created before staging consumed the create choice."""
        with self.governance.store.connect() as db:
            rows = db.execute("""SELECT c.case_id,c.uploaded_by_user_id,c.analysis_json
                                 FROM migration_inventory m
                                 JOIN document_cases c ON c.case_id=m.case_id
                                 WHERE m.status='staged' AND c.status='pending_employee_decision'""").fetchall()
        for row in rows:
            analysis = json.loads(row["analysis_json"] or "{}")
            if analysis.get("exact_duplicate_document_id") or analysis.get("normalized_duplicate_document_id"):
                continue
            self.lifecycle.choose_action(
                case_id=row["case_id"], actor_user_id=row["uploaded_by_user_id"], action="create"
            )

    def inventory(self, root: Path) -> list[MigrationItem]:
        root = root.resolve(); items: list[MigrationItem] = []
        seen_hashes: dict[str, str] = {}
        sources = [path for path in sorted(root.rglob("*"))
                   if path.is_file() and path.suffix.lower() in self.SOURCE_EXTENSIONS
                   and not any(part.startswith(".") for part in path.relative_to(root).parts)]
        for path in sources:
            siblings = [candidate for candidate in sources
                        if candidate.parent == path.parent and candidate.stem == path.stem]
            originals = [candidate for candidate in siblings if candidate.suffix.lower() != ".md"]
            if path.suffix.lower() == ".md" and originals:
                continue
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            original = path if path.suffix.lower() != ".md" else path
            markdown_path = next((candidate for candidate in siblings if candidate.suffix.lower() == ".md"), None)
            if path.suffix.lower() == ".md":
                markdown_path = path
            relative = original.relative_to(root).as_posix()
            unreadable = False
            try:
                original_bytes = original.read_bytes()
                markdown = markdown_path.read_text(encoding="utf-8-sig", errors="replace") if markdown_path else ""
            except OSError:
                original_bytes, markdown, unreadable = b"", "", True
            metadata, body = parse_frontmatter(markdown)
            content_digest = hashlib.sha256(body.encode("utf-8") if markdown_path else original_bytes).hexdigest()
            digest = hashlib.sha256(original_bytes + b"\0" + body.encode("utf-8")).hexdigest()
            document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"kahle-migration:{relative}"))
            version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"kahle-migration:{relative}:{digest}"))
            relative_parts = path.relative_to(root).parts
            knowledgebase_slug = relative_parts[0] if len(relative_parts) > 1 else ""
            with self.governance.store.connect() as db:
                existing = db.execute(
                    "SELECT version_id,knowledgebase_slug,metadata_override_json "
                    "FROM migration_inventory WHERE path=?",
                    (relative,),
                ).fetchone()
            if existing and existing["version_id"] == version_id and existing["metadata_override_json"]:
                metadata = json.loads(existing["metadata_override_json"])
                knowledgebase_slug = existing["knowledgebase_slug"]
            missing = self._missing_requirements(metadata, knowledgebase_slug)
            if unreadable:
                missing = tuple(sorted(set(missing) | {"source_readable"}))
            risk = self.injection.inspect(body).risk if markdown_path else "pending"
            conversion_quality, conversion_issues = self.quality.inspect(body) if markdown_path else ("pending", ())
            if unreadable:
                conversion_quality, conversion_issues = "failed", ("source_unreadable",)
            status = "quarantine" if unreadable or risk in {"high", "critical"} or content_digest in seen_hashes or conversion_quality == "failed" else (
                "ready_to_stage" if not missing else "metadata_required"
            )
            seen_hashes[content_digest] = relative
            deadline = add_workdays(self.today(), 30).isoformat()
            item = MigrationItem(
                relative, relative, markdown_path.relative_to(root).as_posix() if markdown_path else None,
                knowledgebase_slug, document_id, version_id, status, missing, risk,
                conversion_quality, conversion_issues, deadline,
            )
            with self.governance.store.connect() as db:
                db.execute("""INSERT INTO migration_inventory
                    (path,knowledgebase_slug,document_id,version_id,status,missing_json,prompt_injection_risk,case_id,updated_at,
                     original_path,markdown_path,conversion_quality,conversion_issues_json,transition_deadline)
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, datetime('now'), ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET document_id=excluded.document_id,
                    version_id=excluded.version_id,
                    status=CASE WHEN migration_inventory.version_id=excluded.version_id
                                      AND migration_inventory.status IN ('staged','transition_expired','excluded')
                                THEN migration_inventory.status ELSE excluded.status END,
                    missing_json=excluded.missing_json,
                    prompt_injection_risk=excluded.prompt_injection_risk, updated_at=excluded.updated_at,
                    original_path=excluded.original_path,markdown_path=excluded.markdown_path,
                    conversion_quality=excluded.conversion_quality,conversion_issues_json=excluded.conversion_issues_json,
                    transition_deadline=CASE WHEN migration_inventory.version_id=excluded.version_id
                                             THEN COALESCE(migration_inventory.transition_deadline,excluded.transition_deadline)
                                             ELSE excluded.transition_deadline END,
                    transition_status=CASE WHEN migration_inventory.version_id=excluded.version_id
                                           THEN migration_inventory.transition_status ELSE 'pending' END""",
                    (relative, item.knowledgebase_slug, document_id, version_id, status,
                     json.dumps(missing), risk, item.original_path, item.markdown_path,
                     conversion_quality, json.dumps(conversion_issues), deadline))
                self._sync_tasks(db, item)
                stored = db.execute(
                    "SELECT status,transition_deadline,exclusion_reason,excluded_by,excluded_at "
                    "FROM migration_inventory WHERE path=?", (relative,),
                ).fetchone()
            items.append(replace(
                item, status=stored["status"], transition_deadline=stored["transition_deadline"],
                exclusion_reason=stored["exclusion_reason"], excluded_by=stored["excluded_by"],
                excluded_at=stored["excluded_at"],
            ))
        return items

    def _missing_requirements(self, metadata: dict[str, str], knowledgebase_slug: str) -> tuple[str, ...]:
        missing = {field for field in self.REQUIRED if not metadata.get(field)}
        with self.governance.store.connect() as db:
            known_kb = db.execute(
                "SELECT knowledgebase_id FROM knowledgebases WHERE slug=? AND status='active'",
                (knowledgebase_slug,),
            ).fetchone()
        if not known_kb:
            missing.add("knowledgebase")
        owner_email = metadata.get("owner", "").casefold()
        if owner_email:
            with self.governance.store.connect() as db:
                owner = db.execute("SELECT user_id,role FROM portal_users WHERE lower(email)=? AND active=1", (owner_email,)).fetchone()
                kb = db.execute("SELECT knowledgebase_id FROM knowledgebases WHERE slug=? AND status='active'", (knowledgebase_slug,)).fetchone()
                if not owner:
                    missing.add("owner")
                elif owner["role"] not in {"admin", "portal_admin"} and (not kb or not db.execute(
                    "SELECT 1 FROM knowledgebase_access WHERE user_id=? AND knowledgebase_id=? AND can_read=1",
                    (owner["user_id"], kb["knowledgebase_id"] if kb else ""),
                ).fetchone()):
                    missing.add("rights")
        return tuple(sorted(missing))

    def _sync_tasks(self, db, item: MigrationItem) -> None:
        required = {f"metadata:{field}": {"field": field} for field in item.missing}
        if item.conversion_quality in {"failed", "pending"}:
            required["conversion"] = {"quality": item.conversion_quality,
                                      "issues": list(item.conversion_issues)}
        if item.prompt_injection_risk in {"medium", "high", "critical", "pending"}:
            required["security"] = {"prompt_injection_risk": item.prompt_injection_risk}
        for kind, details in required.items():
            task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"migration-task:{item.path}:{kind}"))
            db.execute("""INSERT INTO migration_tasks(task_id,path,kind,status,details_json,created_at)
                          VALUES(?,?,?,'open',?,datetime('now'))
                          ON CONFLICT(path,kind) DO UPDATE SET details_json=excluded.details_json,
                          status=CASE WHEN migration_tasks.status='resolved' THEN 'resolved' ELSE 'open' END""",
                       (task_id, item.path, kind, json.dumps(details, ensure_ascii=False, sort_keys=True)))
        if required:
            placeholders = ",".join("?" for _ in required)
            db.execute(f"UPDATE migration_tasks SET status='resolved',resolved_at=datetime('now') WHERE path=? AND kind NOT IN ({placeholders}) AND status='open'",
                       (item.path, *required.keys()))
        else:
            db.execute("UPDATE migration_tasks SET status='resolved',resolved_at=datetime('now') WHERE path=? AND status='open'", (item.path,))

    def tasks(self, status: str = "open") -> list[dict[str, Any]]:
        if status not in {"open", "resolved", "all"}:
            raise ValueError("invalid_migration_task_status")
        query = "SELECT * FROM migration_tasks"
        values: tuple[str, ...] = ()
        if status != "all":
            query += " WHERE status=?"; values = (status,)
        query += " ORDER BY path,kind"
        with self.governance.store.connect() as db:
            return [{**dict(row), "details": json.loads(row["details_json"])}
                    for row in db.execute(query, values).fetchall()]

    def inventory_items(self) -> list[MigrationItem]:
        with self.governance.store.connect() as db:
            rows = db.execute("SELECT * FROM migration_inventory ORDER BY path").fetchall()
        return [MigrationItem(
            path=row["path"], original_path=row["original_path"] or row["path"],
            markdown_path=row["markdown_path"], knowledgebase_slug=row["knowledgebase_slug"],
            document_id=row["document_id"], version_id=row["version_id"], status=row["status"],
            missing=tuple(json.loads(row["missing_json"])),
            prompt_injection_risk=row["prompt_injection_risk"],
            conversion_quality=row["conversion_quality"],
            conversion_issues=tuple(json.loads(row["conversion_issues_json"])),
            transition_deadline=row["transition_deadline"],
            exclusion_reason=row["exclusion_reason"], excluded_by=row["excluded_by"],
            excluded_at=row["excluded_at"],
        ) for row in rows]

    def exclude(self, relative_path: str, actor_user_id: str, reason: str) -> None:
        actor = self.governance.identity(actor_user_id)
        if actor.role not in {"admin", "portal_admin"}:
            raise ValueError("admin_required")
        reason = reason.strip()
        if len(reason) < 3:
            raise ValueError("migration_exclusion_reason_required")
        with self.governance.store.connect() as db:
            row = db.execute(
                "SELECT status FROM migration_inventory WHERE path=?", (relative_path,),
            ).fetchone()
            if not row:
                raise ValueError("migration_item_unknown")
            if row["status"] in {"staged", "excluded"}:
                raise ValueError("migration_exclusion_not_allowed")
            db.execute(
                """UPDATE migration_inventory SET previous_status=status,status='excluded',
                   exclusion_reason=?,excluded_by=?,excluded_at=datetime('now'),updated_at=datetime('now')
                   WHERE path=?""",
                (reason, actor_user_id, relative_path),
            )
            db.execute(
                "UPDATE migration_tasks SET status='resolved',resolved_at=datetime('now') WHERE path=? AND status='open'",
                (relative_path,),
            )
        self.governance.record_audit(
            actor_user_id, "migration_excluded", "migration_item", relative_path,
            {"reason": reason},
        )

    def restore_excluded(self, relative_path: str, actor_user_id: str, reason: str) -> None:
        actor = self.governance.identity(actor_user_id)
        if actor.role not in {"admin", "portal_admin"}:
            raise ValueError("admin_required")
        reason = reason.strip()
        if len(reason) < 3:
            raise ValueError("migration_restore_reason_required")
        with self.governance.store.connect() as db:
            row = db.execute(
                "SELECT * FROM migration_inventory WHERE path=?", (relative_path,),
            ).fetchone()
            if not row or row["status"] != "excluded":
                raise ValueError("migration_item_not_excluded")
            restored_status = row["previous_status"] or "metadata_required"
            db.execute(
                """UPDATE migration_inventory SET status=?,previous_status=NULL,
                   exclusion_reason=NULL,excluded_by=NULL,excluded_at=NULL,updated_at=datetime('now')
                   WHERE path=?""",
                (restored_status, relative_path),
            )
            item = replace(self._item_from_row(row), status=restored_status,
                           exclusion_reason=None, excluded_by=None, excluded_at=None)
            self._sync_tasks(db, item)
            required_kinds = [f"metadata:{field}" for field in item.missing]
            if item.conversion_quality in {"failed", "pending"}:
                required_kinds.append("conversion")
            if item.prompt_injection_risk in {"medium", "high", "critical", "pending"}:
                required_kinds.append("security")
            if required_kinds:
                placeholders = ",".join("?" for _ in required_kinds)
                db.execute(
                    f"UPDATE migration_tasks SET status='open',resolved_at=NULL WHERE path=? AND kind IN ({placeholders})",
                    (relative_path, *required_kinds),
                )
        self.governance.record_audit(
            actor_user_id, "migration_restored", "migration_item", relative_path,
            {"reason": reason},
        )

    @staticmethod
    def _item_from_row(row) -> MigrationItem:
        return MigrationItem(
            path=row["path"], original_path=row["original_path"] or row["path"],
            markdown_path=row["markdown_path"], knowledgebase_slug=row["knowledgebase_slug"],
            document_id=row["document_id"], version_id=row["version_id"], status=row["status"],
            missing=tuple(json.loads(row["missing_json"])),
            prompt_injection_risk=row["prompt_injection_risk"],
            conversion_quality=row["conversion_quality"],
            conversion_issues=tuple(json.loads(row["conversion_issues_json"])),
            transition_deadline=row["transition_deadline"], exclusion_reason=row["exclusion_reason"],
            excluded_by=row["excluded_by"], excluded_at=row["excluded_at"],
        )

    def review_file(self, root: Path, relative_path: str, kind: str) -> Path:
        """Resolve only an inventoried original or Markdown file for admin review."""
        if kind not in {"original", "markdown"}:
            raise ValueError("invalid_migration_file_kind")
        with self.governance.store.connect() as db:
            row = db.execute(
                "SELECT original_path,markdown_path FROM migration_inventory WHERE path=?",
                (relative_path,),
            ).fetchone()
        if not row:
            raise ValueError("migration_item_unknown")
        stored_path = row["original_path"] if kind == "original" else row["markdown_path"]
        if not stored_path:
            raise ValueError("migration_review_file_unavailable")
        resolved_root = root.resolve()
        target = (resolved_root / stored_path).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("migration_path_outside_root") from exc
        if not target.is_file():
            raise ValueError("migration_review_file_unavailable")
        return target

    def resolve_metadata(self, relative_path: str, actor_user_id: str, *, owner_email: str,
                         confidentiality: str, authority_type: str,
                         authority_level: int, scope: dict[str, Any],
                         knowledgebase_id: str | None = None) -> None:
        actor = self.governance.identity(actor_user_id)
        if actor.role not in {"admin", "portal_admin"}:
            raise ValueError("admin_required")
        owners = self.governance.list_identities(actor_user_id)
        owner = next((item for item in owners if item.active and item.email.casefold() == owner_email.casefold()), None)
        if not owner or confidentiality not in {"internal", "restricted", "confidential"}:
            raise ValueError("valid_owner_and_confidentiality_required")
        if not owner.manager_user_id:
            raise ValueError("migration_owner_manager_required")
        if authority_level not in range(1, 7) or not authority_type.strip():
            raise ValueError("valid_authority_required")
        override = {"owner": owner.email, "confidentiality": confidentiality,
                    "authority_type": authority_type.strip(), "authority_level": authority_level,
                    "scope": scope}
        with self.governance.store.connect() as db:
            row = db.execute("SELECT status,prompt_injection_risk,knowledgebase_slug FROM migration_inventory WHERE path=?", (relative_path,)).fetchone()
            if not row:
                raise ValueError("migration_item_unknown")
            if knowledgebase_id:
                kb = db.execute(
                    "SELECT knowledgebase_id,slug FROM knowledgebases WHERE knowledgebase_id=? AND status='active'",
                    (knowledgebase_id,),
                ).fetchone()
            else:
                kb = db.execute(
                    "SELECT knowledgebase_id,slug FROM knowledgebases WHERE slug=? AND status='active'",
                    (row["knowledgebase_slug"],),
                ).fetchone()
            if not kb or (owner.role not in {"admin", "portal_admin"} and not db.execute(
                "SELECT 1 FROM knowledgebase_access WHERE user_id=? AND knowledgebase_id=? AND can_read=1",
                (owner.user_id, kb["knowledgebase_id"]),
            ).fetchone()):
                raise ValueError("migration_owner_read_access_required")
            scope = dict(scope or {})
            scope["knowledgebase_ids"] = [kb["knowledgebase_id"]]
            override["scope"] = scope
            status = "quarantine" if row["prompt_injection_risk"] in {"high", "critical"} else "ready_to_stage"
            db.execute("UPDATE migration_inventory SET metadata_override_json=?,knowledgebase_slug=?,missing_json='[]',status=?,updated_at=datetime('now') WHERE path=?",
                       (json.dumps(override, ensure_ascii=False, sort_keys=True), kb["slug"], status, relative_path))
            db.execute("UPDATE migration_tasks SET status='resolved',resolved_at=datetime('now') WHERE path=? AND kind LIKE 'metadata:%'", (relative_path,))

    def stage(self, root: Path, relative_path: str, portal_admin_user_id: str) -> str:
        root = root.resolve()
        with self.governance.store.connect() as db:
            row = db.execute("SELECT * FROM migration_inventory WHERE path = ?", (relative_path,)).fetchone()
        if not row or row["status"] != "ready_to_stage":
            raise ValueError("migration_item_not_ready")
        source = (root / (row["original_path"] or relative_path)).resolve(); source.relative_to(root)
        markdown_source = (root / row["markdown_path"]).resolve() if row["markdown_path"] else None
        if markdown_source:
            markdown_source.relative_to(root)
        markdown = markdown_source.read_text(encoding="utf-8-sig", errors="replace") if markdown_source else ""
        metadata, body = parse_frontmatter(markdown)
        override = json.loads(row["metadata_override_json"] or "{}")
        metadata = {**metadata, **override}
        owner = next((user for user in self.governance.list_identities(portal_admin_user_id)
                      if user.email.casefold() == metadata["owner"].casefold()), None)
        if not owner:
            raise ValueError("migration_owner_unknown")
        if not owner.manager_user_id:
            raise ValueError("migration_owner_manager_required")
        kb = next((item for item in self.governance.list_knowledgebases(portal_admin_user_id, "upload")
                   if item.slug == row["knowledgebase_slug"]), None)
        if not kb:
            raise ValueError("migration_knowledgebase_unknown")
        if kb.knowledgebase_id not in self.governance.allowed_knowledgebases(owner.user_id, "read"):
            raise ValueError("migration_owner_read_access_required")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        case_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"case:{row['version_id']}"))
        submission = self.lifecycle.submit(
            # Der Owner bestaetigt den Altbestand wie einen eigenen Upload.
            # Der importierende Admin bleibt ueber Migrationstabelle und Audit nachvollziehbar.
            uploaded_by_user_id=owner.user_id, owner_user_id=owner.user_id,
            target_knowledgebase_id=kb.knowledgebase_id, title=metadata.get("title") or source.stem,
            original_filename=source.name, original_file_id=f"legacy://{relative_path}", original_sha256=digest,
            valid_workdays=60, confidentiality=metadata["confidentiality"],
            document_id=row["document_id"], version_id=row["version_id"], case_id=case_id,
        )
        authority_type = str(metadata.get("authority_type") or "").strip()
        try:
            authority_level = int(metadata.get("authority_level") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("valid_authority_required") from exc
        raw_scope = metadata.get("scope", {})
        if isinstance(raw_scope, str):
            try: scope = json.loads(raw_scope)
            except json.JSONDecodeError: scope = {"description": raw_scope}
        else:
            scope = raw_scope
        if not authority_type or authority_level not in range(1, 7) or not isinstance(scope, dict) or not scope:
            raise ValueError("valid_authority_and_scope_required")
        with self.governance.store.connect() as db:
            db.execute("UPDATE document_metadata SET authority_type=?,authority_level=?,scope_json=? WHERE document_id=?",
                       (authority_type, authority_level,
                        json.dumps(scope, ensure_ascii=False, sort_keys=True), submission.document_id))
        if markdown_source:
            data = source.read_bytes()
            if self.ingest:
                self.ingest.inspector.inspect(source.name, data)
                self.ingest.scanner.scan(source.name, data)
            original = self.storage.store(submission.document_id, submission.version_id,
                                          source.suffix.lower().lstrip("."), data)
            self.storage.store_markdown(original, body)
            injection = self.injection.inspect(body)
            conversion_quality, conversion_issues = self.quality.inspect(body)
        else:
            if not self.ingest:
                raise ValueError("migration_conversion_pipeline_required")
            ingested = self.ingest.ingest(submission.document_id, submission.version_id,
                                          source.name, source.read_bytes(), submission.title)
            body = ingested.markdown_path.read_text(encoding="utf-8")
            injection = ingested.injection
            conversion_quality, conversion_issues = ingested.conversion_quality, ingested.conversion_issues
        analysis = self.analyzer.analyze(version_id=submission.version_id, title=submission.title, markdown=body)
        case = self.lifecycle.record_analysis(
            case_id=case_id, normalized_sha256=analysis.normalized_sha256,
            markdown_sha256=hashlib.sha256(body.encode()).hexdigest(),
            analysis=Analysis(
                exact_duplicate_document_id=analysis.exact_document_id,
                cross_kb_matches=tuple(match.document_id for match in analysis.matches
                                       if kb.knowledgebase_id not in match.knowledgebase_ids),
                contradiction_document_ids=analysis.contradiction_document_ids,
                version_candidate_document_ids=tuple(match.document_id for match in analysis.matches if match.version_candidate),
                prompt_injection_risk=injection.risk,
                conversion_quality=conversion_quality,
                notes=tuple(conversion_issues),
                restricted_terms=self.restricted_term_matcher(body),
            ), actor_user_id="migration",
        )
        # Die Auswahl "in den Freigabeprozess übernehmen" ist bereits die
        # Entscheidung für ein neues Dokument. Nur echte Dubletten benötigen
        # danach noch eine gesonderte Auswahl durch den Owner.
        if case.status == "pending_employee_decision":
            case = self.lifecycle.choose_action(
                case_id=case_id,
                actor_user_id=owner.user_id,
                action="create",
            )
        self.corpus.upsert(CorpusDocument(case.document_id, case.version_id, case.title, body,
                                          (kb.knowledgebase_id,), "pending"))
        with self.governance.store.connect() as db:
            db.execute("""UPDATE migration_inventory SET status='staged',case_id=?,prompt_injection_risk=?,
                          conversion_quality=?,conversion_issues_json=?,transition_status='completed',updated_at=datetime('now')
                          WHERE path=?""",
                       (case_id, injection.risk, conversion_quality,
                        json.dumps(conversion_issues), relative_path))
            db.execute("UPDATE migration_tasks SET status='resolved',resolved_at=datetime('now') WHERE path=?", (relative_path,))
        return case_id

    def process_transition_deadlines(self) -> list[str]:
        today = self.today().isoformat()
        with self.governance.store.connect() as db:
            rows = db.execute("""SELECT path FROM migration_inventory
                                 WHERE transition_status='pending' AND transition_deadline<=?
                                 AND status NOT IN ('staged','quarantine','transition_expired','excluded')""", (today,)).fetchall()
            paths = [row["path"] for row in rows]
            if paths:
                placeholders = ",".join("?" for _ in paths)
                db.execute(f"UPDATE migration_inventory SET status='transition_expired',transition_status='expired',updated_at=datetime('now') WHERE path IN ({placeholders})", paths)
        return paths
