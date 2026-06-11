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


def test_raw_mail_query_is_rejected_before_embedding():
    module = load_module()
    raw_mail = """Hallo Herr Langhorst,

ich habe die beiden weiteren DA-Center soweit vorbereitet mit den Daten, die ich habe.
Ich benoetige letztlich noch jeweils die Dokumenten-ID fuer die CSV-Datei.

Fuer Walsrode finde ich aber keinen einzigen Termin in CATCH.

Viele Gruesse
Jan"""

    assert module._is_raw_mail_query(raw_mail) is True


def test_raw_mail_without_signoff_is_rejected_before_embedding():
    module = load_module()
    raw_mail = """Hallo Herr Langhorst,
ich habe die beiden weiteren DA-Center soweit vorbereitet mit den Daten, die ich habe.
Ich benoetige letztlich noch jeweils die Dokumenten-ID fuer die CSV-Datei,
die fuer das jeweilige Center abgerufen werden soll aus dem GUDAT-System.
Fuer Walsrode finde ich aber keinen einzigen Termin in CATCH.
Das liegt vermutlich daran, dass die abgerufene Quelldatei gudat_4357.csv 12 Spalte hat."""

    assert module._is_raw_mail_query(raw_mail) is True


def test_answer_mail_command_with_raw_mail_is_rejected_before_embedding():
    module = load_module()
    raw_mail = """Beantworte die Mail:
Hallo Herr Langhorst,
ich habe die beiden weiteren DA-Center soweit vorbereitet mit den Daten, die ich habe.
Ich benoetige letztlich noch jeweils die Dokumenten-ID fuer die CSV-Datei.
Fuer Walsrode finde ich aber keinen einzigen Termin in CATCH."""

    assert module._is_raw_mail_query(raw_mail) is True


def test_compact_internal_question_is_not_rejected_as_raw_mail():
    module = load_module()

    assert module._is_raw_mail_query("Welche Oeffnungszeiten hat der Standort Walsrode?") is False


if __name__ == "__main__":
    test_prefer_top_source_keeps_recovery_chunks_and_drops_unrelated_tail()
    test_raw_mail_query_is_rejected_before_embedding()
    test_raw_mail_without_signoff_is_rejected_before_embedding()
    test_answer_mail_command_with_raw_mail_is_rejected_before_embedding()
    test_compact_internal_question_is_not_rejected_as_raw_mail()
    print("rag chat direct qdrant tests passed")
