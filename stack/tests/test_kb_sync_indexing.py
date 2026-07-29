from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYNC_PATH = ROOT / "kb-sync" / "app" / "kb_sync.py"


def load_module():
    sys.modules.setdefault("requests", types.SimpleNamespace())
    sys.modules.setdefault("docx", types.SimpleNamespace(Document=object))
    sys.modules.setdefault("pypdf", types.SimpleNamespace(PdfReader=object))

    watchdog = types.ModuleType("watchdog")
    watchdog_events = types.ModuleType("watchdog.events")
    watchdog_observers = types.ModuleType("watchdog.observers")
    watchdog_events.FileSystemEvent = object
    watchdog_events.FileSystemEventHandler = object
    watchdog_observers.Observer = object
    sys.modules.setdefault("watchdog", watchdog)
    sys.modules.setdefault("watchdog.events", watchdog_events)
    sys.modules.setdefault("watchdog.observers", watchdog_observers)

    spec = importlib.util.spec_from_file_location("kb_sync", SYNC_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_markdown_can_be_excluded_from_rag_index(tmp_path):
    module = load_module()
    root = tmp_path / "kahlekontext"
    root.mkdir()
    excluded = root / "README_Hannover.md"
    excluded.write_text("---\ntitle: Hannover\nrag_index: false\n---\nPlaceholder", encoding="utf-8")
    curated = root / "KB_KAHLE_Hannover.md"
    curated.write_text("---\ntitle: Standort Hannover\n---\nAdresse", encoding="utf-8")

    files = module.iter_collection_files(root, (".md",))

    assert files == [curated]

