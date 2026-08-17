from pathlib import Path
from types import SimpleNamespace
import threading

import app.kb_sync as kb_sync
from app.canonical_inventory import CanonicalInventory
from app.hybrid_sync import CanonicalIndexDocument


def test_incremental_version_sync_bootstraps_full_index_when_snapshot_is_missing(
    tmp_path: Path, monkeypatch,
):
    document = CanonicalIndexDocument(
        document_id="doc-1", version_id="version-1", title="Servicewissen",
        markdown="# Servicewissen\n\nGeprüfter Inhalt.", knowledgebase_ids=("service",),
        owner_email="owner@kahle.de", valid_from="2026-08-14", valid_until="2026-10-14",
        confidentiality="internal", authority="process", source_id="source-1",
        source_url="/wissen/sources/source-1", status="active",
    )
    inventory = CanonicalInventory((document,), (), "digest-1")
    monkeypatch.setattr(kb_sync, "load_portal_inventory", lambda *_: inventory)
    monkeypatch.setattr(
        kb_sync, "load_canonical_inventory",
        lambda *_: CanonicalInventory((), (), "legacy-digest"),
    )
    monkeypatch.setattr(kb_sync, "write_inventory_report", lambda *_: None)

    calls = []
    service = kb_sync.KnowledgebaseSync.__new__(kb_sync.KnowledgebaseSync)
    service.config = SimpleNamespace(
        hybrid_snapshot_path=tmp_path / "missing-bm25.json",
        portal_db_path=tmp_path / "portal.sqlite3",
        portal_files_root=tmp_path / "files",
        kb_root=tmp_path / "knowledgebases",
        state_path=tmp_path / "state" / "kb-sync-state.json",
    )
    service.hybrid_lock = threading.Lock()
    service.hybrid_builder = SimpleNamespace(
        rebuild=lambda documents: calls.append(tuple(documents)) or {
            "collection": "vinci-v3", "documents": 1, "chunks": 2,
        },
        sync_document=lambda _document: (_ for _ in ()).throw(
            AssertionError("incremental sync must not run without a snapshot")
        ),
    )
    service.state = SimpleNamespace(data={}, save=lambda: None)

    report = service.reconcile_hybrid_version("version-1")

    assert report["collection"] == "vinci-v3"
    assert calls == [(document,)]
    assert service.state.data["hybrid"]["status"] == "active"
