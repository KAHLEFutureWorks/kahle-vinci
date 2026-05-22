from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
import asyncio
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "open-webui-tools" / "kb_diagnostics.py"


def load_module(tmp_path: Path):
    kb_root = tmp_path / "knowledgebases"
    state_dir = tmp_path / "state"
    os.environ["KB_ROOT"] = str(kb_root)
    os.environ["KB_STATE_PATH"] = str(state_dir / "kb-sync-state.json")
    os.environ["KB_SYNC_COLLECTIONS"] = "kahleallgemein,kahlekontext"
    sys.modules.setdefault("requests", types.SimpleNamespace(request=None, get=None))
    spec = importlib.util.spec_from_file_location("kb_diagnostics", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module, kb_root, state_dir


def test_filesystem_and_state_helpers(tmp_path):
    module, kb_root, state_dir = load_module(tmp_path)
    collection_root = kb_root / "kahleallgemein"
    collection_root.mkdir(parents=True)
    (collection_root / "README.md").write_text("# Inhalt", encoding="utf-8")
    (collection_root / "ignore.tmp").write_text("x", encoding="utf-8")
    state_dir.mkdir(parents=True)
    (state_dir / "kb-sync-state.json").write_text(
        json.dumps(
            {
                "collections": {
                    "kahleallgemein": {
                        "last_reconcile_at": "2026-05-06T08:00:00Z",
                        "files": {"README.md": {"chunks": 1, "updated_at": "2026-05-06T08:00:00Z"}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    files = module._fs_files("kahleallgemein")
    state = module._load_state()

    assert list(files) == ["README.md"]
    assert state["exists"] is True
    assert state["data"]["collections"]["kahleallgemein"]["files"]["README.md"]["chunks"] == 1
    assert module._collections() == ["kahleallgemein", "kahlekontext"]


def test_kb_list_files_returns_collection_file_inventory(tmp_path):
    module, kb_root, _state_dir = load_module(tmp_path)
    collection_root = kb_root / "kahlerichtlinien"
    collection_root.mkdir(parents=True)
    (collection_root / "A.md").write_text("# A", encoding="utf-8")
    (collection_root / "B.txt").write_text("B", encoding="utf-8")
    (collection_root / "ignore.tmp").write_text("x", encoding="utf-8")

    def fake_collection_report(collection):
        files = []
        for rel_path, fs_info in module._fs_files(collection).items():
            files.append(
                {
                    "source_path": rel_path,
                    "doc_id": f"{collection}/{rel_path}",
                    "size_bytes": fs_info["size_bytes"],
                    "state_chunks": None,
                    "qdrant_chunks": 0,
                    "state_updated_at": "",
                    "indexed": False,
                }
            )
        return {
            "collection": collection,
            "filesystem_files": len(files),
            "qdrant_docs": 0,
            "state_files": 0,
            "last_reconcile_at": "",
            "issues": {
                "missing_in_qdrant": [],
                "orphan_in_qdrant": [],
                "missing_in_state": [],
                "state_without_file": [],
            },
            "files": files,
        }

    module._collection_report = fake_collection_report

    result = json.loads(asyncio.run(module.Tools().kb_list_files("kahlerichtlinien")))

    assert result["ok"] is True
    assert result["collection"] == "kahlerichtlinien"
    assert result["count"] == 2
    assert [item["source_path"] for item in result["files"]] == ["A.md", "B.txt"]


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        test_filesystem_and_state_helpers(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_kb_list_files_returns_collection_file_inventory(Path(tmp))
    print("kb diagnostics helper tests passed")
