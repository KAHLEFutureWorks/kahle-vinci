from datetime import date
from pathlib import Path

from app.canonical_inventory import load_canonical_inventory


def test_only_complete_active_current_documents_are_indexable(tmp_path: Path):
    kb = tmp_path / "service"
    kb.mkdir()
    (kb / "active.md").write_text("""---
document_id: doc-1
version_id: v-1
owner: owner@kahle.de
valid_from: 2026-08-01
valid_until: 2026-09-01
status: active
title: Servicewissen
knowledgebase_ids: [service, verkauf]
---
# Service
Aktion A1b gilt.
""", encoding="utf-8")
    (kb / "legacy.md").write_text("# Altbestand", encoding="utf-8")
    (kb / "expired.md").write_text("""---
document_id: doc-2
version_id: v-2
owner: owner@kahle.de
valid_from: 2026-01-01
valid_until: 2026-02-01
status: active
---
Alt.
""", encoding="utf-8")
    inventory = load_canonical_inventory(tmp_path, today=date(2026, 8, 6))
    assert [document.document_id for document in inventory.documents] == ["doc-1"]
    assert inventory.documents[0].knowledgebase_ids == ("service", "verkauf")
    assert {candidate.path for candidate in inventory.migration_candidates} == {"service/legacy.md", "service/expired.md"}
