import sqlite3
from datetime import date
from pathlib import Path

from app.canonical_inventory import load_portal_inventory


def test_portal_inventory_contains_only_active_published_current_version(tmp_path: Path):
    db_path = tmp_path / "portal.sqlite3"
    files = tmp_path / "files"
    db = sqlite3.connect(db_path)
    db.executescript("""
        CREATE TABLE portal_users (user_id TEXT PRIMARY KEY, email TEXT NOT NULL);
        CREATE TABLE canonical_documents (
            document_id TEXT PRIMARY KEY, title TEXT NOT NULL, owner_user_id TEXT NOT NULL,
            confidentiality TEXT NOT NULL, active_version_id TEXT
        );
        CREATE TABLE document_versions (
            version_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, valid_from TEXT,
            valid_until TEXT, status TEXT NOT NULL
        );
        CREATE TABLE document_publications (
            document_id TEXT NOT NULL, knowledgebase_id TEXT NOT NULL, status TEXT NOT NULL
        );
        INSERT INTO portal_users VALUES ('owner', 'owner@kahle.de');
        INSERT INTO canonical_documents VALUES ('doc-active', 'Aktiv', 'owner', 'internal', 'v-active');
        INSERT INTO canonical_documents VALUES ('doc-pending', 'Entwurf', 'owner', 'internal', NULL);
        INSERT INTO document_versions VALUES ('v-active', 'doc-active', '2026-08-01', '2026-09-01', 'active');
        INSERT INTO document_versions VALUES ('v-pending', 'doc-pending', NULL, NULL, 'ready_to_activate');
        INSERT INTO document_publications VALUES ('doc-active', 'service', 'active');
        INSERT INTO document_publications VALUES ('doc-active', 'verkauf', 'active');
        INSERT INTO document_publications VALUES ('doc-pending', 'service', 'pending');
    """)
    db.commit()
    db.close()
    rag = files / "doc-active" / "v-active" / "rag.md"
    rag.parent.mkdir(parents=True)
    rag.write_text("# Freigegeben\nNur dieser Inhalt.", encoding="utf-8")

    inventory = load_portal_inventory(db_path, files, today=date(2026, 8, 6))

    assert [document.document_id for document in inventory.documents] == ["doc-active"]
    assert inventory.documents[0].knowledgebase_ids == ("service", "verkauf")
    assert inventory.documents[0].source_url == "/wissen/api/portal/sources/v-active"


def test_portal_inventory_fails_closed_when_active_markdown_is_missing(tmp_path: Path):
    assert load_portal_inventory(tmp_path / "missing.sqlite3", tmp_path / "files").documents == ()


def test_portal_inventory_loads_retrieval_metadata_from_sidecar_table(tmp_path: Path):
    db_path = tmp_path / "portal.sqlite3"
    files = tmp_path / "files"
    db = sqlite3.connect(db_path)
    db.executescript("""
        CREATE TABLE portal_users (user_id TEXT PRIMARY KEY, email TEXT NOT NULL);
        CREATE TABLE canonical_documents (
            document_id TEXT PRIMARY KEY, title TEXT NOT NULL, owner_user_id TEXT NOT NULL,
            confidentiality TEXT NOT NULL, active_version_id TEXT
        );
        CREATE TABLE document_versions (
            version_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, valid_from TEXT,
            valid_until TEXT, status TEXT NOT NULL
        );
        CREATE TABLE document_publications (
            document_id TEXT NOT NULL, knowledgebase_id TEXT NOT NULL, status TEXT NOT NULL
        );
        CREATE TABLE document_retrieval_metadata (
            version_id TEXT PRIMARY KEY, domain TEXT NOT NULL, document_type TEXT NOT NULL,
            topics_json TEXT NOT NULL, evidence_capabilities_json TEXT NOT NULL,
            source_provider TEXT NOT NULL, classification_status TEXT NOT NULL,
            classifier_version TEXT NOT NULL, confidence REAL NOT NULL
        );
        INSERT INTO portal_users VALUES ('owner', 'owner@kahle.de');
        INSERT INTO canonical_documents VALUES ('doc-1', 'WPS Anleitung', 'owner', 'internal', 'v-1');
        INSERT INTO document_versions VALUES ('v-1', 'doc-1', '2026-08-01', '2026-09-01', 'active');
        INSERT INTO document_publications VALUES ('doc-1', 'service', 'active');
        INSERT INTO document_retrieval_metadata VALUES (
            'v-1', 'internal_systems', 'work_instruction', '["WPS"]',
            '["procedure"]', 'knowledge_portal', 'inferred',
            'kahle.retrieval-metadata.v1', 0.95
        );
    """)
    db.commit()
    db.close()
    rag = files / "doc-1" / "v-1" / "rag.md"
    rag.parent.mkdir(parents=True)
    rag.write_text("# WPS\n1. Termin öffnen.\n2. Speichern.", encoding="utf-8")

    document = load_portal_inventory(db_path, files, today=date(2026, 8, 6)).documents[0]

    assert document.domain == "internal_systems"
    assert document.document_type == "work_instruction"
    assert document.topics == ("WPS",)
    assert document.evidence_capabilities == ("procedure",)
    assert document.source_provider == "knowledge_portal"
    assert document.classification_status == "inferred"
    assert document.classification_version == "kahle.retrieval-metadata.v1"
    assert document.classification_confidence == .95
