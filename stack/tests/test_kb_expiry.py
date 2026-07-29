from __future__ import annotations

import importlib.util
import sqlite3
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "owui-file-proxy" / "app" / "kb_expiry.py"


def load_module():
    spec = importlib.util.spec_from_file_location("kb_expiry", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _create_webui_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("create table user (id text, name text, email text, role text)")
    con.execute(
        "insert into user values (?, ?, ?, ?)",
        ("admin-1", "Vinci Admin", "admin@example.invalid", "admin"),
    )
    con.execute(
        "insert into user values (?, ?, ?, ?)",
        ("user-1", "Normal User", "user@example.invalid", "user"),
    )
    con.commit()
    con.close()


def test_scan_supports_frontmatter_and_filename_dates(tmp_path):
    module = load_module()
    kb_root = tmp_path / "knowledgebases"
    context = kb_root / "kahlekontext"
    context.mkdir(parents=True)
    (context / "Standort.md").write_text(
        "---\n"
        "title: Standort Hannover\n"
        "valid_until: 2026-08-05\n"
        "notify_before_days: 14\n"
        "rag_index: true\n"
        "---\n"
        "Inhalt",
        encoding="utf-8",
    )
    (context / "Preisliste_gueltig-bis_01.08.2026.pdf").write_bytes(b"%PDF")
    (context / "Entwurf.md").write_text(
        "---\nvalid_until: 2026-08-01\nrag_index: false\n---\nEntwurf",
        encoding="utf-8",
    )

    documents = module.scan_expiring_documents(kb_root, today=date(2026, 7, 28))

    assert [item["title"] for item in documents] == [
        "Preisliste gueltig bis 01.08.2026",
        "Standort Hannover",
    ]
    assert documents[0]["days_remaining"] == 4
    assert documents[1]["days_remaining"] == 8


def test_sync_creates_deduplicated_admin_tasks_and_cancels_resolved(tmp_path):
    module = load_module()
    kb_root = tmp_path / "knowledgebases"
    context = kb_root / "kahlekontext"
    context.mkdir(parents=True)
    document = context / "Richtlinie.md"
    document.write_text(
        "---\ntitle: Richtlinie\nvalid_until: 2026-08-01\nnotify_before_days: 14\n---\nText",
        encoding="utf-8",
    )
    webui_db = tmp_path / "webui.db"
    tasks_db = tmp_path / "tasks.db"
    _create_webui_db(webui_db)

    first = module.sync_expiry_tasks(
        kb_root,
        tasks_db,
        webui_db,
        today=date(2026, 7, 28),
        dry_run=False,
    )
    second = module.sync_expiry_tasks(
        kb_root,
        tasks_db,
        webui_db,
        today=date(2026, 7, 28),
        dry_run=False,
    )

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["updated"] == 1
    con = sqlite3.connect(tasks_db)
    row = con.execute(
        "select user_id, status, source_chat_id, due_date from tasks"
    ).fetchone()
    assert row == ("admin-1", "open", "system:kb-expiry", "2026-08-01")
    con.close()

    document.write_text(
        "---\ntitle: Richtlinie\nvalid_until: 2027-08-01\nnotify_before_days: 14\n---\nText",
        encoding="utf-8",
    )
    resolved = module.sync_expiry_tasks(
        kb_root,
        tasks_db,
        webui_db,
        today=date(2026, 7, 28),
        dry_run=False,
    )

    assert resolved["cancelled"] == 1
    con = sqlite3.connect(tasks_db)
    status = con.execute("select status from tasks").fetchone()[0]
    con.close()
    assert status == "cancelled"
