from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "open-webui-tools" / "rag_chat_direct_qdrant.py"


def load_module():
    class FakeField:
        def __init__(self, default=None, description=""):
            self.default = default

    class FakeBaseModel:
        def __init__(self):
            for name, value in self.__class__.__dict__.items():
                if isinstance(value, FakeField):
                    setattr(self, name, value.default)

    sys.modules.setdefault("pydantic", types.SimpleNamespace(BaseModel=FakeBaseModel, Field=FakeField))
    sys.modules.setdefault("requests", types.SimpleNamespace(post=None))
    spec = importlib.util.spec_from_file_location("rag_chat_direct_qdrant", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_prefer_top_source_keeps_recovery_chunks_and_drops_unrelated_tail():
    module = load_module()
    chunks = [
        {
            "collection": "kahlerichtlinien",
            "source_path": "Arbeitsanweisung_Recovery-Gutscheine.md",
            "chunk_index": 0,
            "score": 0.723,
            "text": "Recovery-Gutschein einloesen",
        },
        {
            "collection": "kahlerichtlinien",
            "source_path": "Arbeitsanweisung_Recovery-Gutscheine.md",
            "chunk_index": 1,
            "score": 0.683,
            "text": "GUTSRECO setzen",
        },
        {
            "collection": "kahlerichtlinien",
            "source_path": "Arbeitsanweisung_Optimierung_Kundenpflege_SB.md",
            "chunk_index": 3,
            "score": 0.471,
            "text": "E-Mail-Adresse in VaudisX erfassen",
        },
    ]

    filtered = module._prefer_top_source_chunks(chunks, max_chunks=6, score_floor=0.45)

    assert [chunk["source_path"] for chunk in filtered] == [
        "Arbeitsanweisung_Recovery-Gutscheine.md",
        "Arbeitsanweisung_Recovery-Gutscheine.md",
    ]


if __name__ == "__main__":
    test_prefer_top_source_keeps_recovery_chunks_and_drops_unrelated_tail()
    print("rag chat direct qdrant tests passed")
