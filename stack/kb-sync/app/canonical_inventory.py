from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

try:
    from .hybrid_sync import CanonicalIndexDocument, MigrationCandidate, parse_frontmatter
except ImportError:  # pragma: no cover
    from hybrid_sync import CanonicalIndexDocument, MigrationCandidate, parse_frontmatter


REQUIRED = ("document_id", "version_id", "owner", "valid_from", "valid_until", "status")


@dataclass(frozen=True)
class CanonicalInventory:
    documents: tuple[CanonicalIndexDocument, ...]
    migration_candidates: tuple[MigrationCandidate, ...]
    digest: str


def load_canonical_inventory(root: Path, *, today: date | None = None) -> CanonicalInventory:
    today = today or date.today()
    documents: list[CanonicalIndexDocument] = []
    candidates: list[MigrationCandidate] = []
    digest = hashlib.sha256()
    if not root.exists():
        return CanonicalInventory((), (), digest.hexdigest())
    for kb_dir in sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")):
        for path in sorted(kb_dir.rglob("*.md")):
            markdown = path.read_text(encoding="utf-8-sig", errors="replace")
            metadata, body = parse_frontmatter(markdown)
            if str(metadata.get("rag_index", "true")).casefold() in {"false", "no", "0"}:
                continue
            relative = path.relative_to(root).as_posix()
            missing = tuple(field for field in REQUIRED if not metadata.get(field))
            if missing:
                candidates.append(MigrationCandidate(relative, kb_dir.name, missing))
                continue
            kb_values = metadata.get("knowledgebase_ids") or metadata.get("knowledgebases") or (kb_dir.name,)
            if isinstance(kb_values, str):
                kb_values = tuple(item.strip() for item in kb_values.split(",") if item.strip())
            document = CanonicalIndexDocument(
                document_id=str(metadata["document_id"]), version_id=str(metadata["version_id"]),
                title=str(metadata.get("title") or path.stem.replace("_", " ")), markdown=body,
                knowledgebase_ids=tuple(kb_values), owner_email=str(metadata["owner"]),
                valid_from=str(metadata["valid_from"]), valid_until=str(metadata["valid_until"]),
                confidentiality=str(metadata.get("confidentiality") or "internal"),
                authority=str(metadata.get("authority") or "information"),
                source_id=str(metadata.get("source_id") or metadata["version_id"]),
                source_url=f"/wissen/sources/{metadata.get('source_id') or metadata['version_id']}",
                status=str(metadata["status"]),
            )
            try:
                document.validate(today)
            except Exception:
                candidates.append(MigrationCandidate(relative, kb_dir.name, ("active_current_approval",)))
                continue
            digest.update(relative.encode("utf-8"))
            digest.update(hashlib.sha256(markdown.encode("utf-8")).digest())
            documents.append(document)
    return CanonicalInventory(tuple(documents), tuple(candidates), digest.hexdigest())


def load_portal_inventory(db_path: Path, files_root: Path, *, today: date | None = None) -> CanonicalInventory:
    """Load only currently active, published portal versions for indexing."""
    today = today or date.today()
    digest = hashlib.sha256()
    if not db_path.exists():
        return CanonicalInventory((), (), digest.hexdigest())
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        has_metadata = bool(connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_metadata'"
        ).fetchone())
        authority_fields = (
            "COALESCE(meta.authority_type, 'information_or_training') authority_type, "
            "COALESCE(meta.authority_level, 6) authority_level"
            if has_metadata else
            "'information_or_training' authority_type, 6 authority_level"
        )
        metadata_join = "LEFT JOIN document_metadata meta ON meta.document_id=d.document_id" if has_metadata else ""
        rows = connection.execute(f"""
            SELECT d.document_id, d.title, u.email AS owner_email, d.confidentiality,
                   {authority_fields}, v.version_id, v.valid_from, v.valid_until,
                   GROUP_CONCAT(p.knowledgebase_id) AS knowledgebase_ids
            FROM canonical_documents d
            JOIN portal_users u ON u.user_id = d.owner_user_id
            {metadata_join}
            JOIN document_versions v ON v.version_id = d.active_version_id AND v.status = 'active'
            JOIN document_publications p ON p.document_id = d.document_id AND p.status = 'active'
            GROUP BY d.document_id, v.version_id
            ORDER BY d.document_id, v.version_id
        """).fetchall()
    finally:
        connection.close()
    documents: list[CanonicalIndexDocument] = []
    for row in rows:
        markdown_path = files_root / row["document_id"] / row["version_id"] / "rag.md"
        if not markdown_path.is_file():
            continue
        markdown = markdown_path.read_text(encoding="utf-8-sig", errors="replace")
        document = CanonicalIndexDocument(
            document_id=row["document_id"], version_id=row["version_id"], title=row["title"],
            markdown=markdown, knowledgebase_ids=tuple(sorted(set(row["knowledgebase_ids"].split(",")))),
            owner_email=row["owner_email"], valid_from=row["valid_from"], valid_until=row["valid_until"],
            confidentiality=row["confidentiality"] or "internal",
            authority=f"{row['authority_level']}:{row['authority_type']}",
            source_id=row["version_id"], source_url=f"/wissen/api/portal/sources/{row['version_id']}", status="active",
        )
        document.validate(today)
        digest.update(row["version_id"].encode("utf-8"))
        digest.update(hashlib.sha256(markdown.encode("utf-8")).digest())
        digest.update(row["knowledgebase_ids"].encode("utf-8"))
        documents.append(document)
    return CanonicalInventory(tuple(documents), (), digest.hexdigest())


def write_inventory_report(inventory: CanonicalInventory, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({
        "digest": inventory.digest,
        "indexable_documents": len(inventory.documents),
        "migration_candidates": [candidate.__dict__ for candidate in inventory.migration_candidates],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
