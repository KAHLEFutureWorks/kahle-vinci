from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path

from backup_restore import create_backup, restore_backup, validate_restored_portal
from bm25_snapshot import BM25Snapshot
from canonical_inventory import load_portal_inventory
from hybrid_sync import HybridIndexBuilder


class MemoryQdrant:
    def __init__(self):
        self.staging = ""
        self.points: list[dict] = []
        self.alias = ""

    def create_staging(self, name: str) -> None:
        self.staging = name

    def upsert(self, collection: str, points: list[dict]) -> None:
        assert collection == self.staging
        self.points.extend(points)

    def activate_alias(self, alias: str, staging: str) -> None:
        assert staging == self.staging and self.points
        self.alias = alias


class DeterministicEmbeddings:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text) % 17), float(text.count("Service")), 1.0] for text in texts]


def build_portal(root: Path) -> Path:
    portal = root / "portal-data"
    files = portal / "files" / "doc-service" / "version-1"
    files.mkdir(parents=True)
    (files / "original.md").write_text("# Service\nOriginal", encoding="utf-8")
    (files / "rag.md").write_text(
        "# Serviceprozess\n\nEine Garantieanfrage wird über den beschriebenen Serviceprozess eingereicht.",
        encoding="utf-8",
    )
    db = sqlite3.connect(portal / "wissensportal.sqlite3")
    db.executescript(
        """
        CREATE TABLE portal_users(user_id TEXT PRIMARY KEY,email TEXT);
        CREATE TABLE canonical_documents(
          document_id TEXT PRIMARY KEY,title TEXT,owner_user_id TEXT,confidentiality TEXT,active_version_id TEXT
        );
        CREATE TABLE document_metadata(
          document_id TEXT PRIMARY KEY,authority_type TEXT,authority_level INTEGER,scope_json TEXT
        );
        CREATE TABLE document_versions(
          version_id TEXT PRIMARY KEY,document_id TEXT,status TEXT,valid_from TEXT,valid_until TEXT
        );
        CREATE TABLE document_publications(document_id TEXT,knowledgebase_id TEXT,status TEXT);
        INSERT INTO portal_users VALUES ('owner','owner@kahle.de');
        INSERT INTO canonical_documents VALUES ('doc-service','Serviceprozess','owner','restricted','version-1');
        INSERT INTO document_metadata VALUES ('doc-service','process_instruction',5,'{}');
        INSERT INTO document_versions VALUES ('version-1','doc-service','active','2026-08-06','2099-12-31');
        INSERT INTO document_publications VALUES ('doc-service','service','active');
        """
    )
    db.commit()
    db.close()
    return portal


def test_encrypted_restore_rebuilds_authoritative_hybrid_index(tmp_path: Path):
    portal = build_portal(tmp_path / "source")
    key = os.urandom(32)
    backup = tmp_path / "backup" / "acceptance.kahlebackup"
    result = create_backup({"portal-data": portal}, backup, key)
    assert result.files == 3

    restored = tmp_path / "restored"
    restore_backup(backup, restored, key)
    validate_restored_portal(restored)
    inventory = load_portal_inventory(
        restored / "portal-data" / "wissensportal.sqlite3",
        restored / "portal-data" / "files",
        today=date(2026, 8, 6),
    )
    assert len(inventory.documents) == 1
    assert inventory.documents[0].authority == "5:process_instruction"

    qdrant = MemoryQdrant()
    snapshot = tmp_path / "bm25.json"
    report = HybridIndexBuilder(
        qdrant, DeterministicEmbeddings(), alias="vinci_acceptance", snapshot_path=snapshot,
    ).rebuild(list(inventory.documents), today=date(2026, 8, 6))
    assert report["documents"] == 1 and report["chunks"] >= 1
    assert qdrant.alias == "vinci_acceptance"
    assert qdrant.points[0]["payload"]["source_url"] == "/wissen/api/portal/sources/version-1"
    assert qdrant.points[0]["payload"]["knowledgebase_ids"] == ["service"]
    assert qdrant.points[0]["vector"]["bm25"]["indices"]
    assert BM25Snapshot.load(snapshot).build_id == report["collection"]
