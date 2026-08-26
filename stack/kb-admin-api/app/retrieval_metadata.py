from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CLASSIFIER_VERSION = "kahle.retrieval-metadata.v2"
DOMAINS = {
    "knowledge_governance", "data_protection", "internal_systems",
    "employee_directory", "internal_processes", "internal_locations",
    "internal_general",
}
DOCUMENT_TYPES = {
    "work_instruction", "process_description", "system_overview",
    "contact_directory", "policy", "knowledge_document", "responsibility_matrix",
    "location_profile",
}
EVIDENCE_CAPABILITIES = {
    "approval_workflow", "procedure", "system_overview", "contact_details",
    "factual_support", "explicit_relationship", "explicit_usage_scope",
    "opening_hours", "location_department_overview",
}


@dataclass(frozen=True)
class RetrievalMetadata:
    domain: str
    document_type: str
    topics: tuple[str, ...]
    evidence_capabilities: tuple[str, ...]
    source_provider: str = "knowledge_portal"
    classification_status: str = "inferred"
    confidence: float = 0.9


@dataclass(frozen=True)
class EvidenceRelation:
    subject_type: str
    subject: str
    predicate: str
    object: str
    evidence_span: str


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()


class RetrievalMetadataClassifier:
    """Deterministic, versioned classification for retrieval planning.

    The classifier describes what a source can prove. It never edits the
    uploaded file and deliberately does not infer undocumented relationships.
    """

    def classify(self, title: str, markdown: str) -> RetrievalMetadata:
        combined = f"{title}\n{markdown}"
        folded = _fold(combined)

        opening_hours = bool(
            re.search(r"\b(?:offnungszeiten|oeffnungszeiten|offnungszeit|oeffnungszeit)\b", folded)
            or (
                re.search(r"\bmo\s*[-–]\s*fr\b", folded)
                and re.search(r"\bsa(?:mstag)?\b", folded)
            )
        )
        location_profile = "standort" in folded and opening_hours

        if location_profile:
            domain = "internal_locations"
        elif (
            any(term in folded for term in ("wissensportal", "arbeitsanweisung"))
            or ("dokument" in folded and "freigab" in folded)
        ):
            domain = "knowledge_governance"
        elif any(term in folded for term in ("datenschutz", "werbewiderspruch", "kundensperre")):
            domain = "data_protection"
        elif any(term in folded for term in ("system", "software", "anwendung", "dms")):
            domain = "internal_systems"
        elif any(term in folded for term in ("kontakt", "ansprechpartner", "durchwahl")):
            domain = "employee_directory"
        else:
            domain = "internal_processes"

        numbered_steps = len(re.findall(r"(?m)^\s*(?:\d+[.)]|[-*])\s+", markdown or ""))
        procedural_terms = sum(
            term in folded
            for term in ("schritt", "zuerst", "anschliessend", "danach", "abschliessend")
        )
        action_patterns = (
            r"\bo?ffn\w*", r"\bnavigier\w*", r"\bklick\w*", r"\bwahl\w*",
            r"\bwaehl\w*", r"\b(?:eingeb\w*|gib)\b", r"\berfass\w*",
            r"\bspeicher\w*", r"\bbestaetig\w*", r"\berstell\w*",
        )
        action_count = sum(bool(re.search(pattern, folded)) for pattern in action_patterns)
        procedure = numbered_steps >= 2 or procedural_terms >= 2 or action_count >= 3
        approval_workflow = all(
            any(term in folded for term in alternatives)
            for alternatives in (
                ("pruf", "kontroll"),
                ("freigab", "freigeb", "genehmig"),
                ("veroffentlich", "publizier"),
            )
        )

        if location_profile:
            document_type = "location_profile"
        elif "arbeitsanweisung" in folded or (procedure and approval_workflow):
            document_type = "work_instruction"
        elif procedure or "prozessbeschreibung" in folded:
            document_type = "process_description"
        elif domain == "internal_systems":
            document_type = "system_overview"
        elif domain == "employee_directory":
            document_type = "contact_directory"
        elif any(term in folded for term in ("richtlinie", "policy", "leitlinie")):
            document_type = "policy"
        else:
            document_type = "knowledge_document"

        capabilities: list[str] = []
        if approval_workflow:
            capabilities.append("approval_workflow")
        if procedure:
            capabilities.append("procedure")
        if document_type == "system_overview" and not procedure:
            capabilities.append("system_overview")
        if domain == "employee_directory":
            capabilities.append("contact_details")
        if self.relations(markdown):
            capabilities.append("explicit_relationship")
        explicit_usage_scope = any(
            re.search(
                r"\b(?:wird|werden|ist|sind)\b.{0,100}"
                r"\b(?:an|in|fur)\b.{0,40}\b(?:standort|filial)\w*\b",
                sentence,
            )
            and re.search(r"\b(?:eingesetzt|genutzt|verwendet|verfugbar|ausgerollt)\w*\b", sentence)
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", folded)
        )
        if explicit_usage_scope:
            capabilities.append("explicit_usage_scope")
        if opening_hours:
            capabilities.append("opening_hours")
        if opening_hours and all(
            department in folded for department in ("verkauf", "service", "teiledienst")
        ):
            capabilities.append("location_department_overview")
        if not capabilities:
            capabilities.append("factual_support")

        topics = tuple(dict.fromkeys(
            token.upper() if token.isupper() else token
            for token in re.findall(r"\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9.-]{1,30}\b", combined)
            if token.casefold() not in {
                "der", "die", "das", "ein", "eine", "und", "oder", "im", "in",
                "mit", "für", "von", "zur", "zum", "kahle",
            }
        ))[:20]
        review_required = capabilities == ["factual_support"] and document_type == "knowledge_document"
        return RetrievalMetadata(
            domain=domain,
            document_type=document_type,
            topics=topics,
            evidence_capabilities=tuple(capabilities),
            classification_status="review_required" if review_required else "inferred",
            confidence=0.55 if review_required else 0.95,
        )

    def relations(self, markdown: str) -> tuple[EvidenceRelation, ...]:
        """Extract only relationships asserted inside one literal sentence."""
        relations: list[EvidenceRelation] = []
        sentences = [
            item.strip()
            for item in re.findall(r"[^.!?\n]+[.!?]?", str(markdown or ""))
            if item.strip()
        ]
        for sentence in sentences:
            support = re.fullmatch(
                r"(?iu)Für\s+den\s+technischen\s+Support\s+von\s+"
                r"(?P<object>[A-ZÄÖÜ][\w.-]+)\s+ist\s+"
                r"(?P<subject>[A-ZÄÖÜ][\w.-]+\s+[A-ZÄÖÜ][\w.-]+)\s+"
                r"zuständig[.!?]?",
                sentence,
            )
            if support:
                relations.append(EvidenceRelation(
                    subject_type="person",
                    subject=support.group("subject"),
                    predicate="technical_support_for",
                    object=support.group("object"),
                    evidence_span=sentence,
                ))
                continue
            direct = re.fullmatch(
                r"(?iu)(?P<subject>[A-ZÄÖÜ][\w.-]+\s+[A-ZÄÖÜ][\w.-]+)\s+"
                r"(?P<predicate>betreut|begleitet|verantwortet)\s+"
                r"(?P<object>[A-ZÄÖÜ][\w.-]+)[.!?]?",
                sentence,
            )
            if direct:
                relations.append(EvidenceRelation(
                    subject_type="person",
                    subject=direct.group("subject"),
                    predicate={
                        "betreut": "supports",
                        "begleitet": "contributes_to",
                        "verantwortet": "responsible_for",
                    }[direct.group("predicate").casefold()],
                    object=direct.group("object"),
                    evidence_span=sentence,
                ))
        return tuple(relations)


class RetrievalMetadataStore:
    """Portal-owned sidecar metadata keyed by immutable document version."""

    def __init__(self, db_path: str | Path, classifier: RetrievalMetadataClassifier | None = None):
        self.db_path = Path(db_path)
        self.classifier = classifier or RetrievalMetadataClassifier()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_retrieval_metadata (
                    version_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    topics_json TEXT NOT NULL DEFAULT '[]',
                    evidence_capabilities_json TEXT NOT NULL DEFAULT '[]',
                    source_provider TEXT NOT NULL,
                    classification_status TEXT NOT NULL,
                    classifier_version TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    classified_at TEXT NOT NULL,
                    confirmed_by_user_id TEXT,
                    confirmed_at TEXT
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS document_evidence_relations (
                    version_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    evidence_span TEXT NOT NULL,
                    classifier_version TEXT NOT NULL,
                    PRIMARY KEY (version_id,subject_type,subject,predicate,object,evidence_span)
                )
                """
            )
            relation_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(document_evidence_relations)")
            }
            if "document_id" not in relation_columns:
                db.execute(
                    "ALTER TABLE document_evidence_relations ADD COLUMN document_id TEXT NOT NULL DEFAULT ''"
                )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_retrieval_metadata_domain "
                "ON document_retrieval_metadata(domain, document_type)"
            )
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(document_retrieval_metadata)")
            }
            if "confirmed_by_user_id" not in columns:
                db.execute(
                    "ALTER TABLE document_retrieval_metadata ADD COLUMN confirmed_by_user_id TEXT"
                )
            if "confirmed_at" not in columns:
                db.execute(
                    "ALTER TABLE document_retrieval_metadata ADD COLUMN confirmed_at TEXT"
                )

    def classify_version(
        self,
        *,
        document_id: str,
        version_id: str,
        title: str,
        markdown: str,
        content_sha256: str | None = None,
    ) -> bool:
        digest = content_sha256 or hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        metadata = self.classifier.classify(title, markdown)
        relations = self.classifier.relations(markdown)
        with self._connect() as db:
            current = db.execute(
                "SELECT content_sha256,classifier_version FROM document_retrieval_metadata "
                "WHERE version_id=?",
                (version_id,),
            ).fetchone()
            if current and current["content_sha256"] == digest and current["classifier_version"] == CLASSIFIER_VERSION:
                return False
            db.execute(
                """
                INSERT INTO document_retrieval_metadata (
                    version_id,document_id,domain,document_type,topics_json,
                    evidence_capabilities_json,source_provider,classification_status,
                    classifier_version,confidence,content_sha256,classified_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(version_id) DO UPDATE SET
                    document_id=excluded.document_id,
                    domain=excluded.domain,
                    document_type=excluded.document_type,
                    topics_json=excluded.topics_json,
                    evidence_capabilities_json=excluded.evidence_capabilities_json,
                    source_provider=excluded.source_provider,
                    classification_status=excluded.classification_status,
                    classifier_version=excluded.classifier_version,
                    confidence=excluded.confidence,
                    content_sha256=excluded.content_sha256,
                    classified_at=excluded.classified_at
                """,
                (
                    version_id,
                    document_id,
                    metadata.domain,
                    metadata.document_type,
                    json.dumps(metadata.topics, ensure_ascii=False),
                    json.dumps(metadata.evidence_capabilities, ensure_ascii=False),
                    metadata.source_provider,
                    metadata.classification_status,
                    CLASSIFIER_VERSION,
                    metadata.confidence,
                    digest,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            db.execute("DELETE FROM document_evidence_relations WHERE version_id=?", (version_id,))
            db.executemany(
                """INSERT INTO document_evidence_relations (
                       version_id,document_id,subject_type,subject,predicate,object,evidence_span,classifier_version
                   ) VALUES (?,?,?,?,?,?,?,?)""",
                [
                    (
                        version_id, document_id, relation.subject_type, relation.subject,
                        relation.predicate, relation.object, relation.evidence_span,
                        CLASSIFIER_VERSION,
                    )
                    for relation in relations
                ],
            )
        return True

    def backfill(self, files_root: str | Path, *, dry_run: bool = False) -> dict[str, int]:
        files_root = Path(files_root)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT v.version_id,v.document_id,d.title
                FROM document_versions v
                JOIN canonical_documents d ON d.document_id=v.document_id
                WHERE v.status <> 'purged'
                ORDER BY v.document_id,v.version_id
                """
            ).fetchall()
        report = {"classified": 0, "unchanged": 0, "missing_files": 0}
        for row in rows:
            path = files_root / row["document_id"] / row["version_id"] / "rag.md"
            if not path.is_file():
                report["missing_files"] += 1
                continue
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if dry_run:
                with self._connect() as db:
                    current = db.execute(
                        "SELECT content_sha256,classifier_version "
                        "FROM document_retrieval_metadata WHERE version_id=?",
                        (row["version_id"],),
                    ).fetchone()
                changed = not (
                    current
                    and current["content_sha256"] == digest
                    and current["classifier_version"] == CLASSIFIER_VERSION
                )
            else:
                changed = self.classify_version(
                    document_id=row["document_id"],
                    version_id=row["version_id"],
                    title=row["title"],
                    markdown=raw.decode("utf-8-sig", errors="replace"),
                    content_sha256=digest,
                )
            report["classified" if changed else "unchanged"] += 1
        return report

    def for_version(self, version_id: str) -> dict[str, object] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM document_retrieval_metadata WHERE version_id=?",
                (version_id,),
            ).fetchone()
            relations = db.execute(
                """SELECT subject_type,subject,predicate,object,evidence_span
                   FROM document_evidence_relations WHERE version_id=?
                   ORDER BY subject,predicate,object,evidence_span""",
                (version_id,),
            ).fetchall()
        if not row:
            return None
        payload = dict(row)
        payload["topics"] = json.loads(str(payload.pop("topics_json") or "[]"))
        payload["evidence_capabilities"] = json.loads(
            str(payload.pop("evidence_capabilities_json") or "[]")
        )
        payload["relations"] = [dict(item) for item in relations]
        return payload

    def review_required(self) -> list[dict[str, object]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM document_retrieval_metadata
                   WHERE classification_status='review_required'
                   ORDER BY document_id,version_id"""
            ).fetchall()
        values = []
        for row in rows:
            payload = dict(row)
            payload["topics"] = json.loads(str(payload.pop("topics_json") or "[]"))
            payload["evidence_capabilities"] = json.loads(
                str(payload.pop("evidence_capabilities_json") or "[]")
            )
            values.append(payload)
        return values

    def confirm(
        self,
        *,
        version_id: str,
        domain: str,
        document_type: str,
        topics: tuple[str, ...],
        evidence_capabilities: tuple[str, ...],
        actor_user_id: str,
    ) -> dict[str, object]:
        domain = str(domain or "").strip()
        document_type = str(document_type or "").strip()
        capabilities = tuple(dict.fromkeys(
            str(item or "").strip() for item in evidence_capabilities if str(item or "").strip()
        ))
        if domain not in DOMAINS:
            raise ValueError("invalid_retrieval_domain")
        if document_type not in DOCUMENT_TYPES:
            raise ValueError("invalid_document_type")
        if not capabilities or not set(capabilities).issubset(EVIDENCE_CAPABILITIES):
            raise ValueError("invalid_evidence_capabilities")
        if not str(actor_user_id or "").strip():
            raise ValueError("confirming_actor_required")
        clean_topics = tuple(dict.fromkeys(
            str(item or "").strip() for item in topics if str(item or "").strip()
        ))[:20]
        stamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            current = db.execute(
                "SELECT version_id FROM document_retrieval_metadata WHERE version_id=?",
                (version_id,),
            ).fetchone()
            if not current:
                raise ValueError("retrieval_metadata_not_found")
            if "explicit_relationship" in capabilities:
                relation = db.execute(
                    "SELECT 1 FROM document_evidence_relations WHERE version_id=? LIMIT 1",
                    (version_id,),
                ).fetchone()
                if not relation:
                    raise ValueError("explicit_relationship_evidence_required")
            db.execute(
                """UPDATE document_retrieval_metadata
                   SET domain=?,document_type=?,topics_json=?,evidence_capabilities_json=?,
                       classification_status='confirmed',confidence=1.0,
                       confirmed_by_user_id=?,confirmed_at=?
                   WHERE version_id=?""",
                (
                    domain, document_type, json.dumps(clean_topics, ensure_ascii=False),
                    json.dumps(capabilities, ensure_ascii=False), actor_user_id, stamp, version_id,
                ),
            )
        result = self.for_version(version_id)
        if result is None:  # pragma: no cover - protected by the transaction above
            raise ValueError("retrieval_metadata_not_found")
        return result
