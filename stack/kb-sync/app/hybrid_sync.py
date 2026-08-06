from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import requests

try:
    from .hybrid_index import BM25Corpus, ParentChildChunker
    from .bm25_snapshot import BM25Snapshot
except ImportError:  # pragma: no cover
    from hybrid_index import BM25Corpus, ParentChildChunker
    from bm25_snapshot import BM25Snapshot


HYBRID_SCHEMA_VERSION = 2


class HybridSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class CanonicalIndexDocument:
    document_id: str
    version_id: str
    title: str
    markdown: str
    knowledgebase_ids: tuple[str, ...]
    owner_email: str
    valid_from: str
    valid_until: str
    confidentiality: str
    authority: str
    source_id: str
    source_url: str
    status: str = "active"

    def validate(self, today: date | None = None) -> None:
        today = today or date.today()
        if not self.document_id or not self.version_id or not self.knowledgebase_ids:
            raise HybridSyncError("canonical_identity_incomplete")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", self.owner_email):
            raise HybridSyncError("owner_email_invalid")
        try:
            start, end = date.fromisoformat(self.valid_from), date.fromisoformat(self.valid_until)
        except ValueError as exc:
            raise HybridSyncError("validity_invalid") from exc
        if end < start:
            raise HybridSyncError("validity_invalid")
        if self.status != "active":
            raise HybridSyncError("only_active_versions_may_be_indexed")
        if end < today:
            raise HybridSyncError("expired_version_may_not_be_indexed")
        if not self.source_id or not self.source_url.startswith("/"):
            raise HybridSyncError("source_reference_invalid")


@dataclass(frozen=True)
class MigrationCandidate:
    path: str
    knowledgebase_id: str
    missing_fields: tuple[str, ...]


class DenseEmbeddings(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class QdrantHybridClient:
    def __init__(self, base_url: str, dense_dimension: int = 1024):
        self.base_url, self.dense_dimension = base_url.rstrip("/"), dense_dimension

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = requests.request(method, f"{self.base_url}{path}", timeout=120, **kwargs)
        if response.status_code >= 400:
            raise HybridSyncError(f"qdrant_{method.lower()}_{response.status_code}")
        return response.json() if response.content else {}

    def create_staging(self, name: str) -> None:
        self.request("PUT", f"/collections/{name}", json={
            "vectors": {"dense": {"size": self.dense_dimension, "distance": "Cosine"}},
            "sparse_vectors": {"bm25": {}},
            "on_disk_payload": True,
        })
        for field, schema in (
            ("knowledgebase_ids", "keyword"), ("status", "keyword"), ("version_id", "keyword"),
            ("document_id", "keyword"), ("valid_until", "datetime"), ("confidentiality", "keyword"),
        ):
            self.request("PUT", f"/collections/{name}/index", json={"field_name": field, "field_schema": schema})

    def upsert(self, collection: str, points: list[dict[str, Any]]) -> None:
        if points:
            self.request("PUT", f"/collections/{collection}/points?wait=true", json={"points": points})

    def activate_alias(self, alias: str, staging: str) -> None:
        aliases = self.request("GET", "/aliases").get("result", {}).get("aliases", [])
        actions: list[dict[str, Any]] = []
        if any(item.get("alias_name") == alias for item in aliases):
            actions.append({"delete_alias": {"alias_name": alias}})
        actions.append({"create_alias": {"collection_name": staging, "alias_name": alias}})
        self.request("POST", "/collections/aliases", json={"actions": actions})


class HybridIndexBuilder:
    def __init__(self, qdrant: QdrantHybridClient, embeddings: DenseEmbeddings,
                 chunker: ParentChildChunker | None = None, alias: str = "vinci_knowledge",
                 snapshot_path: Path | None = None):
        self.qdrant, self.embeddings = qdrant, embeddings
        self.chunker = chunker or ParentChildChunker()
        self.alias = alias
        self.snapshot_path = snapshot_path

    def rebuild(self, documents: list[CanonicalIndexDocument], *, today: date | None = None) -> dict[str, Any]:
        today = today or date.today()
        if not documents:
            raise HybridSyncError("empty_index_not_activated")
        for document in documents:
            document.validate(today)
        staging = f"{self.alias}_v{HYBRID_SCHEMA_VERSION}_{uuid.uuid4().hex[:12]}"
        chunks: list[tuple[CanonicalIndexDocument, Any]] = []
        for document in documents:
            chunks.extend((document, chunk) for chunk in self.chunker.chunk(document.document_id, document.markdown))
        corpus = BM25Corpus(chunk.content for _, chunk in chunks)
        self.qdrant.create_staging(staging)
        for offset in range(0, len(chunks), 16):
            batch = chunks[offset:offset + 16]
            dense = self.embeddings.embed([chunk.content for _, chunk in batch])
            if len(dense) != len(batch):
                raise HybridSyncError("embedding_count_mismatch")
            points = []
            for (document, chunk), dense_vector in zip(batch, dense):
                payload = {
                    "schema_version": HYBRID_SCHEMA_VERSION,
                    "build_id": staging,
                    "document_id": document.document_id,
                    "version_id": document.version_id,
                    "title": document.title,
                    "owner_email": document.owner_email,
                    "knowledgebase_ids": list(document.knowledgebase_ids),
                    "status": "active",
                    "published": True,
                    "valid_from": document.valid_from,
                    "valid_until": document.valid_until,
                    "confidentiality": document.confidentiality,
                    "authority": document.authority,
                    "source_id": document.source_id,
                    "source_url": document.source_url,
                    "child_id": chunk.child_id,
                    "parent_id": chunk.parent_id,
                    "chunk_order": chunk.order,
                    "heading_path": list(chunk.heading_path),
                    "content": chunk.content,
                    "parent_content": chunk.parent_content,
                    "chunk_kind": chunk.kind,
                }
                points.append({
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document.version_id}:{chunk.child_id}")),
                    "vector": {"dense": dense_vector, "bm25": corpus.document_vector(chunk.content).qdrant()},
                    "payload": payload,
                })
            self.qdrant.upsert(staging, points)
        # Publish the sparse vocabulary first. Until the alias switches, queries fail closed
        # on the build-id filter instead of mixing generations.
        if self.snapshot_path:
            BM25Snapshot.from_corpus(staging, corpus).save_atomic(self.snapshot_path)
        self.qdrant.activate_alias(self.alias, staging)
        return {"alias": self.alias, "collection": staging, "documents": len(documents), "chunks": len(chunks)}


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    if not markdown.startswith("---"):
        return {}, markdown
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n?", markdown, re.S)
    if not match:
        return {}, markdown
    metadata: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"\'')
        if value.startswith("[") and value.endswith("]"):
            metadata[key.strip()] = tuple(item.strip().strip('"\'') for item in value[1:-1].split(",") if item.strip())
        else:
            metadata[key.strip()] = value
    return metadata, markdown[match.end():]


REQUIRED_MIGRATION_FIELDS = ("document_id", "version_id", "owner", "valid_from", "valid_until", "status")


def inventory_legacy_files(root: Path) -> list[MigrationCandidate]:
    candidates: list[MigrationCandidate] = []
    for kb_dir in sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")):
        for path in sorted(kb_dir.rglob("*.md")):
            metadata, _ = parse_frontmatter(path.read_text(encoding="utf-8-sig", errors="replace"))
            if str(metadata.get("rag_index", "true")).casefold() in {"false", "no", "0"}:
                continue
            missing = tuple(field for field in REQUIRED_MIGRATION_FIELDS if not metadata.get(field))
            if missing:
                candidates.append(MigrationCandidate(path.relative_to(root).as_posix(), kb_dir.name, missing))
    return candidates


def write_migration_inventory(root: Path, output: Path) -> list[MigrationCandidate]:
    candidates = inventory_legacy_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps([candidate.__dict__ for candidate in candidates], ensure_ascii=False, indent=2), encoding="utf-8")
    return candidates
