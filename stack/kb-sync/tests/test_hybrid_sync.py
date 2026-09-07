from datetime import date
import hashlib
import json
from pathlib import Path

import pytest

from app.hybrid_sync import (
    CanonicalIndexDocument, HybridIndexBuilder, HybridSyncError, inventory_legacy_files,
    QdrantHybridClient,
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


class IncrementalQdrant(Qdrant):
    def __init__(self):
        super().__init__(); self.calls = []
    def active_collection(self, alias): return "vinci-live"
    def set_publication(self, collection, *, published, point_ids=None, document_id=None, exclude_version_id=None):
        self.calls.append(("publish", published, point_ids, document_id, exclude_version_id))
    def delete_document_versions(self, collection, document_id, *, exclude_version_id=None):
        self.calls.append(("delete", document_id, exclude_version_id))
    def delete_version(self, collection, document_id, version_id):
        self.calls.append(("delete_version", document_id, version_id))
    def upsert(self, collection, points):
        self.calls.append(("upsert", collection, [point["payload"]["published"] for point in points]))
        super().upsert(collection, points)


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
    assert qdrant.created.startswith("vinci_knowledge_v3_")
    assert qdrant.activated == ("vinci_knowledge", qdrant.created)
    point = qdrant.points[0]
    assert set(point["vector"]) == {"dense", "bm25"}
    assert point["payload"]["knowledgebase_ids"] == ["service", "verkauf"]
    assert point["payload"]["status"] == "active"
    assert point["payload"]["source_url"] == "/wissen/sources/src-1"
    assert report["chunks"] >= 1


def test_rebuild_projects_portal_sidecar_metadata_into_every_chunk():
    qdrant = Qdrant()
    HybridIndexBuilder(qdrant, Embeddings()).rebuild([
        canonical(
            domain="internal_systems",
            document_type="work_instruction",
            topics=("WPS",),
            evidence_capabilities=("procedure",),
            source_provider="knowledge_portal",
            classification_status="inferred",
            classification_version="kahle.retrieval-metadata.v1",
            classification_confidence=.95,
        )
    ], today=date(2026, 8, 6))

    payload = qdrant.points[0]["payload"]
    assert payload["domain"] == "internal_systems"
    assert payload["document_type"] == "work_instruction"
    assert payload["topics"] == ["WPS"]
    assert payload["evidence_capabilities"] == ["procedure"]
    assert payload["source_provider"] == "knowledge_portal"
    assert payload["classification_status"] == "inferred"
    assert payload["classification_version"] == "kahle.retrieval-metadata.v1"
    assert payload["classification_confidence"] == .95


def test_incremental_sync_only_embeds_one_document_and_switches_visibility_fail_closed():
    qdrant = IncrementalQdrant()
    report = HybridIndexBuilder(qdrant, Embeddings()).sync_document(canonical(), today=date(2026, 8, 6))
    assert report["collection"] == "vinci-live"
    assert [call[0] for call in qdrant.calls] == ["upsert", "publish", "publish", "delete"]
    assert qdrant.calls[0][2] == [False]
    assert qdrant.calls[1][1:] == (False, None, "doc-1", "v-1")
    assert qdrant.calls[2][1] is True
    assert qdrant.calls[3] == ("delete", "doc-1", "v-1")
    assert all(point["payload"]["build_id"] == "vinci-hybrid-v3" for point in qdrant.points)


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


@pytest.mark.parametrize("incremental", [False, True])
def test_both_sync_paths_emit_source_bound_contact_and_hint_payloads(incremental):
    row = "| IT | E-Mail | it@example.invalid | Störungen | gruppenweit |"
    markdown = "\n".join(("# Wissen", "## Kurzindex", "Wer hilft bei Störungen?", "## Funktionskontakte",
        "| Funktion | Kontaktart | Kontaktwert | Verwendungszweck | Geltungsbereich |",
        "| --- | --- | --- | --- | --- |", row))
    qdrant = IncrementalQdrant() if incremental else Qdrant()
    builder = HybridIndexBuilder(qdrant, Embeddings())
    doc = canonical(markdown=markdown)
    if incremental:
        builder.sync_document(doc, today=date(2026, 8, 6))
    else:
        builder.rebuild([doc], today=date(2026, 8, 6))
    payloads = [point["payload"] for point in qdrant.points]
    contacts = [payload for payload in payloads if payload["chunk_kind"] == "functional_contact"]
    assert len(contacts) == 1
    contact = contacts[0]
    assert contact["content"] == contact["parent_content"] == row
    assert contact["functional_contact"]["row_number"] == 7
    expected_key = hashlib.sha256(json.dumps(
        ["IT", "email", "Störungen", "gruppenweit"], ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    assert contact["functional_contact_key"] == expected_key
    assert contact["source_id"] == "src-1"
    assert contact["document_id"] == "doc-1" and contact["version_id"] == "v-1"
    assert contact["published"] is (not incremental)
    hints = [payload for payload in payloads if payload["chunk_kind"] == "retrieval_hint"]
    assert len(hints) == 1
    assert "functional_contact" not in hints[0] and "functional_contact_key" not in hints[0]


def test_contact_key_gets_keyword_index(monkeypatch):
    client = QdrantHybridClient("http://qdrant.invalid")
    calls = []
    monkeypatch.setattr(client, "request", lambda method, path, **kwargs: calls.append((path, kwargs["json"])))
    client.create_staging("synthetic-staging")
    assert ("/collections/synthetic-staging/index", {
        "field_name": "functional_contact_key", "field_schema": "keyword",
    }) in calls


@pytest.mark.parametrize("incremental", [False, True])
@pytest.mark.parametrize("changes", [{"status": "draft"}, {"valid_until": "2026-08-05"}, {"version_id": ""}])
def test_contact_document_cannot_bypass_publication_or_version_validation(incremental, changes):
    qdrant = IncrementalQdrant() if incremental else Qdrant()
    builder = HybridIndexBuilder(qdrant, Embeddings())
    markdown = ("## Funktionskontakte\n"
        "| Funktion | Kontaktart | Kontaktwert | Verwendungszweck | Geltungsbereich |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| IT | E-Mail | it@example.invalid | Störungen | gruppenweit |")
    doc = canonical(markdown=markdown, **changes)
    with pytest.raises(HybridSyncError):
        if incremental:
            builder.sync_document(doc, today=date(2026, 8, 6))
        else:
            builder.rebuild([doc], today=date(2026, 8, 6))
    assert qdrant.points == [] and qdrant.activated is None


def test_contact_incremental_publication_failure_restores_previous_version(monkeypatch):
    qdrant = IncrementalQdrant()
    publish = qdrant.set_publication

    def fail_new_publication(collection, **kwargs):
        if kwargs.get("published") and kwargs.get("point_ids"):
            raise HybridSyncError("synthetic_publication_failure")
        publish(collection, **kwargs)

    monkeypatch.setattr(qdrant, "set_publication", fail_new_publication)
    doc = canonical(markdown=("## Funktionskontakte\n"
        "| Funktion | Kontaktart | Kontaktwert | Verwendungszweck | Geltungsbereich |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| IT | E-Mail | it@example.invalid | Störungen | gruppenweit |"))
    with pytest.raises(HybridSyncError, match="synthetic_publication_failure"):
        HybridIndexBuilder(qdrant, Embeddings()).sync_document(doc, today=date(2026, 8, 6))
    assert any(point["payload"]["chunk_kind"] == "functional_contact" for point in qdrant.points)
    assert qdrant.calls[-2] == ("publish", True, None, "doc-1", "v-1")
    assert qdrant.calls[-1] == ("delete_version", "doc-1", "v-1")
