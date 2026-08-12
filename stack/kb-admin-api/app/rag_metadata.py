from __future__ import annotations

import json
import re
import time
from pathlib import Path

try:
    from .portal_governance import SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import SQLiteGovernanceStore


FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n?", re.S)


def strip_untrusted_frontmatter(markdown: str) -> str:
    return FRONTMATTER.sub("", markdown or "", count=1).lstrip()


def _yaml_value(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(json.dumps(str(item), ensure_ascii=False) for item in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


class RAGMetadataWriter:
    """Materialize trusted workflow metadata without accepting source frontmatter."""

    def __init__(self, store: SQLiteGovernanceStore, files_root: Path):
        self.store, self.files_root = store, files_root

    def write(self, version_id: str, path: Path | None = None) -> Path:
        with self.store.connect() as db:
            row = db.execute(
                """SELECT d.document_id, d.title, d.owner_user_id, owner.email owner_email,
                          d.confidentiality, COALESCE(meta.authority_type, 'information_or_training') authority_type,
                          COALESCE(meta.authority_level, 6) authority_level, COALESCE(meta.scope_json, '{}') scope_json,
                          v.version_id, v.previous_version_id, v.original_filename,
                          v.original_file_id, v.original_sha256, v.markdown_sha256,
                          v.valid_from, v.valid_until, v.status, v.created_at, v.activated_at,
                          GROUP_CONCAT(p.knowledgebase_id) knowledgebase_ids
                   FROM document_versions v JOIN canonical_documents d USING(document_id)
                   JOIN portal_users owner ON owner.user_id=d.owner_user_id
                   LEFT JOIN document_metadata meta ON meta.document_id=d.document_id
                   LEFT JOIN document_publications p ON p.document_id=d.document_id
                   WHERE v.version_id=? GROUP BY v.version_id""",
                (version_id,),
            ).fetchone()
        if not row:
            raise ValueError("unknown_version")
        path = path or (self.files_root / row["document_id"] / row["version_id"] / "rag.md")
        body = strip_untrusted_frontmatter(path.read_text(encoding="utf-8-sig"))
        knowledgebases = sorted(set(filter(None, (row["knowledgebase_ids"] or "").split(","))))
        try:
            scope = json.loads(row["scope_json"] or "{}")
        except json.JSONDecodeError:
            scope = {}
        metadata = {
            "document_id": row["document_id"], "version_id": row["version_id"],
            "title": row["title"], "original_filename": row["original_filename"],
            "original_file_id": row["original_file_id"], "owner_user_id": row["owner_user_id"],
            "owner": row["owner_email"], "owner_email": row["owner_email"],
            "status": row["status"], "confidentiality": row["confidentiality"],
            "authority_type": row["authority_type"], "authority_level": row["authority_level"],
            "scope": json.dumps(scope, ensure_ascii=False, sort_keys=True),
            "knowledgebase_ids": knowledgebases, "valid_from": row["valid_from"],
            "valid_until": row["valid_until"], "rag_index": row["status"] == "active",
            "source_url": f"/wissen/api/portal/sources/{row['version_id']}",
            "previous_version_id": row["previous_version_id"],
            "original_sha256": row["original_sha256"], "markdown_sha256": row["markdown_sha256"],
            "created_at": row["created_at"], "approved_at": row["activated_at"],
        }
        frontmatter = "---\n" + "\n".join(
            f"{key}: {_yaml_value(value)}" for key, value in metadata.items()
        ) + "\n---\n\n"
        content = frontmatter + body.rstrip() + "\n"
        temporary = path.with_suffix(".md.tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        for attempt in range(3):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05 * (attempt + 1))
        return path
