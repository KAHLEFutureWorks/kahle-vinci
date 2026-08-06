import os
import sqlite3
from pathlib import Path

import pytest

from app.backup_restore import BackupError, create_backup, restore_backup, validate_restored_portal


def build_portal(root: Path) -> Path:
    portal = root / "portal-data"
    portal.mkdir(parents=True)
    db = sqlite3.connect(portal / "wissensportal.sqlite3")
    db.execute("CREATE TABLE canonical_documents(document_id TEXT, active_version_id TEXT)")
    db.execute("INSERT INTO canonical_documents VALUES ('doc-1', 'v-1')")
    db.commit(); db.close()
    markdown = portal / "files" / "doc-1" / "v-1" / "rag.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("# Sicheres Wissen", encoding="utf-8")
    return portal


def test_encrypted_backup_roundtrip_and_portal_integrity(tmp_path: Path):
    portal = build_portal(tmp_path / "source")
    key = os.urandom(32)
    backup = tmp_path / "backup" / "daily.kahlebackup"
    result = create_backup({"portal-data": portal}, backup, key)
    assert result.files == 2
    assert b"Sicheres Wissen" not in backup.read_bytes()
    restored = tmp_path / "restored"
    manifest = restore_backup(backup, restored, key)
    assert len(manifest["files"]) == 2
    validate_restored_portal(restored)


def test_restore_rejects_wrong_key_and_nonempty_destination(tmp_path: Path):
    portal = build_portal(tmp_path / "source")
    key = os.urandom(32)
    backup = tmp_path / "daily.kahlebackup"
    create_backup({"portal-data": portal}, backup, key)
    with pytest.raises(Exception):
        restore_backup(backup, tmp_path / "wrong", os.urandom(32))
    occupied = tmp_path / "occupied"; occupied.mkdir(); (occupied / "keep.txt").write_text("keep")
    with pytest.raises(BackupError, match="restore_destination_not_empty"):
        restore_backup(backup, occupied, key)
