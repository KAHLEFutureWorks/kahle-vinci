from datetime import date
from pathlib import Path

import pytest

from app.hybrid_sync import (
    CanonicalIndexDocument, HybridIndexBuilder, HybridSyncError, inventory_legacy_files,
)


class Embeddings:
    def embed(self, texts):
        return [[float(len(text)), 1.0] for text in texts]


class Qdrant:
    def __init__(self):
        self.created = None
        self.points = []
        self.activated = None

    def create_staging(self, name): self.created = name
    def upsert(self, collection, points): self.points.extend(points)
    def activate_alias(self, alias, staging): self.activated = (alias, staging)


def canonical(**changes):
    values = dict(
        document_id="doc-1", version_id="v-1", title="Service", markdown="# Service\n\nAktion A1b gilt.",
        knowledgebase_ids=("service", "verkauf"), owner_email="owner@kahle.de",
        valid_from="2026-08-01", valid_until="2026-10-01", confidentiality="internal",
        authority="process", source_id="src-1", source_url="/wissen/sources/src-1", status="active",
    )
    values.update(changes)
    return CanonicalIndexDocument(**values)


def test_rebuild_writes_dense_sparse_acl_and_source_payload_before_alias_switch():
    qdrant = Qdrant()
    report = HybridIndexBuilder(qdrant, Embeddings()).rebuild([canonical()], today=date(2026, 8, 6))
    assert qdrant.created.startswith("vinci_knowledge_v2_")
    assert qdrant.activated == ("vinci_knowledge", qdrant.created)
    point = qdrant.points[0]
    assert set(point["vector"]) == {"dense", "bm25"}
    assert point["payload"]["knowledgebase_ids"] == ["service", "verkauf"]
    assert point["payload"]["status"] == "active"
    assert point["payload"]["source_url"] == "/wissen/sources/src-1"
    assert report["chunks"] >= 1


def test_expired_or_nonactive_document_can_never_be_activated():
    for document in (canonical(valid_until="2026-08-05"), canonical(status="draft")):
        qdrant = Qdrant()
        with pytest.raises(HybridSyncError):
            HybridIndexBuilder(qdrant, Embeddings()).rebuild([document], today=date(2026, 8, 6))
        assert qdrant.activated is None


def test_legacy_inventory_requires_canonical_metadata(tmp_path: Path):
    kb = tmp_path / "service"
    kb.mkdir()
    (kb / "legacy.md").write_text("# Altes Wissen", encoding="utf-8")
    (kb / "navigation.md").write_text("---\nrag_index: false\n---\n# Navigation", encoding="utf-8")
    candidates = inventory_legacy_files(tmp_path)
    assert len(candidates) == 1
    assert candidates[0].path == "service/legacy.md"
    assert "document_id" in candidates[0].missing_fields
