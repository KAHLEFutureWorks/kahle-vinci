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


HYBRID_SCHEMA_VERSION = 3
HYBRID_BUILD_ID = "vinci-hybrid-v3"
BM25_REFERENCE_LENGTH = 100.0


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
            "sparse_vectors": {"bm25": {"modifier": "idf"}},
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

    def active_collection(self, alias: str) -> str:
        aliases = self.request("GET", "/aliases").get("result", {}).get("aliases", [])
        for item in aliases:
            if item.get("alias_name") == alias:
                return str(item["collection_name"])
        raise HybridSyncError("hybrid_alias_unavailable")

    @staticmethod
    def _document_filter(document_id: str, exclude_version_id: str | None = None) -> dict[str, Any]:
        value: dict[str, Any] = {"must": [{"key": "document_id", "match": {"value": document_id}}]}
        if exclude_version_id:
            value["must_not"] = [{"key": "version_id", "match": {"value": exclude_version_id}}]
        return value

    def set_publication(self, collection: str, *, published: bool,
                        point_ids: list[str] | None = None, document_id: str | None = None,
                        exclude_version_id: str | None = None) -> None:
        selector: dict[str, Any]
        if point_ids is not None:
            selector = {"points": point_ids}
        elif document_id:
            selector = {"filter": self._document_filter(document_id, exclude_version_id)}
        else:  # pragma: no cover - programmer error
            raise HybridSyncError("publication_selector_required")
        self.request("POST", f"/collections/{collection}/points/payload?wait=true", json={
            "payload": {"published": published}, **selector,
        })

    def delete_document_versions(self, collection: str, document_id: str,
                                 *, exclude_version_id: str | None = None) -> None:
        self.request("POST", f"/collections/{collection}/points/delete?wait=true", json={
            "filter": self._document_filter(document_id, exclude_version_id),
        })

    def delete_version(self, collection: str, document_id: str, version_id: str) -> None:
        self.request("POST", f"/collections/{collection}/points/delete?wait=true", json={
            "filter": {"must": [
                {"key": "document_id", "match": {"value": document_id}},
                {"key": "version_id", "match": {"value": version_id}},
            ]},
        })


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
        corpus = BM25Corpus((chunk.content for _, chunk in chunks), average_length=BM25_REFERENCE_LENGTH)
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
                    "build_id": HYBRID_BUILD_ID,
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
            BM25Snapshot.from_corpus(HYBRID_BUILD_ID, corpus).save_atomic(self.snapshot_path)
        self.qdrant.activate_alias(self.alias, staging)
        return {"alias": self.alias, "collection": staging, "documents": len(documents), "chunks": len(chunks)}

    def sync_document(self, document: CanonicalIndexDocument, *, today: date | None = None) -> dict[str, Any]:
        """Replace one document in-place without rebuilding unrelated vectors."""
        document.validate(today or date.today())
        collection = self.qdrant.active_collection(self.alias)
        chunks = self.chunker.chunk(document.document_id, document.markdown)
        dense_vectors = self.embeddings.embed([chunk.content for chunk in chunks])
        if len(dense_vectors) != len(chunks):
            raise HybridSyncError("embedding_count_mismatch")
        corpus = BM25Corpus((chunk.content for chunk in chunks), average_length=BM25_REFERENCE_LENGTH)
        points: list[dict[str, Any]] = []
        for chunk, dense_vector in zip(chunks, dense_vectors):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document.version_id}:{chunk.child_id}"))
            points.append({
                "id": point_id,
                "vector": {"dense": dense_vector, "bm25": corpus.document_vector(chunk.content).qdrant()},
                "payload": {
                    "schema_version": HYBRID_SCHEMA_VERSION, "build_id": HYBRID_BUILD_ID,
                    "document_id": document.document_id, "version_id": document.version_id,
                    "title": document.title, "owner_email": document.owner_email,
                    "knowledgebase_ids": list(document.knowledgebase_ids), "status": "active",
                    "published": False, "valid_from": document.valid_from,
                    "valid_until": document.valid_until, "confidentiality": document.confidentiality,
                    "authority": document.authority, "source_id": document.source_id,
                    "source_url": document.source_url, "child_id": chunk.child_id,
                    "parent_id": chunk.parent_id, "chunk_order": chunk.order,
                    "heading_path": list(chunk.heading_path), "content": chunk.content,
                    "parent_content": chunk.parent_content, "chunk_kind": chunk.kind,
                },
            })
        point_ids = [point["id"] for point in points]
        self.qdrant.upsert(collection, points)
        old_hidden = False
        try:
            self.qdrant.set_publication(
                collection, published=False, document_id=document.document_id,
                exclude_version_id=document.version_id,
            )
            old_hidden = True
            self.qdrant.set_publication(collection, published=True, point_ids=point_ids)
            self.qdrant.delete_document_versions(
                collection, document.document_id, exclude_version_id=document.version_id,
            )
        except Exception:
            if old_hidden:
                self.qdrant.set_publication(
                    collection, published=True, document_id=document.document_id,
                    exclude_version_id=document.version_id,
                )
            self.qdrant.delete_version(collection, document.document_id, document.version_id)
            raise
        return {"alias": self.alias, "collection": collection, "documents": 1, "chunks": len(chunks)}


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
