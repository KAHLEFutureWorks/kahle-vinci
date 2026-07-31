from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
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


def test_dynamic_collection_discovery_merges_configured_and_filesystem_bases():
    module = load_module()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "dashboard-testwissen").mkdir()
        (root / ".versions").mkdir()
        previous = os.environ.get("KB_ROOT")
        os.environ["KB_ROOT"] = str(root)
        try:
            assert module._discover_collections("kahleallgemein") == [
                "dashboard-testwissen",
                "kahleallgemein",
            ]
        finally:
            if previous is None:
                os.environ.pop("KB_ROOT", None)
            else:
                os.environ["KB_ROOT"] = previous


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


def test_exact_identifier_routes_to_matching_source_only():
    module = load_module()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        collection = root / "testkb"
        collection.mkdir()
        (collection / "A1a_ki_safety_readiness_check.md").write_text("A1a", encoding="utf-8")
        (collection / "A1b_ki_tool_knowledge_analyse.md").write_text("A1b", encoding="utf-8")
        previous = os.environ.get("KB_ROOT")
        os.environ["KB_ROOT"] = str(root)
        try:
            matches = module._matching_sources(["testkb"], "Was weißt du über A1a?")
            assert matches == {"testkb": ["A1a_ki_safety_readiness_check.md"]}
        finally:
            if previous is None:
                os.environ.pop("KB_ROOT", None)
            else:
                os.environ["KB_ROOT"] = previous


def test_source_filter_is_sent_to_qdrant():
    module = load_module()
    captured = {}

    def fake_post(_url, payload, headers=None, timeout=60):
        captured.update(payload)
        return {"result": []}

    module._post_json = fake_post
    module._search_collection(
        "http://qdrant:6333",
        "testkb",
        [0.1, 0.2],
        6,
        60,
        source_paths=["A1a_ki_safety_readiness_check.md"],
    )
    assert captured["filter"]["should"][0]["match"]["value"] == "A1a_ki_safety_readiness_check.md"


def test_followup_query_keeps_prior_product_identifier():
    module = load_module()
    messages = [
        {"role": "user", "content": "Was weißt du intern über A1a?"},
        {"role": "assistant", "content": "A1a ist der Safety-Readiness-Check."},
        {"role": "user", "content": "Gib mir mehr zum Assessment-Framework"},
    ]
    expanded = module._expand_followup_query("Gib mir mehr zum Assessment-Framework", messages)
    assert expanded.endswith("Bezug: a1a")

def test_enumeration_retrieval_collects_distributed_numbered_headings():
    module = load_module()
    chunks = [
        {"collection": "testkb", "source_path": "konzept.md", "chunk_index": 43, "score": 0.559, "text": "Alle 5 Dimensionen werden bewertet."},
        {"collection": "testkb", "source_path": "konzept.md", "chunk_index": 2, "score": 0.0, "text": "## 4. Assessment-Framework: 5 Readiness-Dimensionen\n\n### Dimension 1: Governance\n\nDetails"},
        {"collection": "testkb", "source_path": "konzept.md", "chunk_index": 3, "score": 0.0, "text": "### Dimension 1: Governance\n\nWeitere Details"},
        {"collection": "testkb", "source_path": "konzept.md", "chunk_index": 6, "score": 0.0, "text": "### Dimension 2: Tool-Landschaft"},
        {"collection": "testkb", "source_path": "konzept.md", "chunk_index": 10, "score": 0.0, "text": "### Dimension 3: Datenpraktiken"},
        {"collection": "testkb", "source_path": "konzept.md", "chunk_index": 15, "score": 0.0, "text": "### Dimension 4: Prozesse"},
        {"collection": "testkb", "source_path": "konzept.md", "chunk_index": 19, "score": 0.0, "text": "### Dimension 5: Dokumentation"},
    ]

    selected = module._select_structural_chunks(
        chunks,
        "Was sind die 5 Dimensionen?",
        max_chunks=6,
    )

    assert [chunk["chunk_index"] for chunk in selected] == [2, 6, 10, 15, 19]


def test_enumeration_retrieval_is_generic_for_phases():
    module = load_module()
    chunks = [
        {
            "collection": "prozesse",
            "source_path": "rollout.md",
            "chunk_index": index,
            "score": 0.0,
            "text": f"## Phase {index}: Abschnitt {index}",
        }
        for index in range(1, 5)
    ]

    selected = module._select_structural_chunks(
        chunks,
        "Welche 3 Phasen hat der Rollout?",
        max_chunks=6,
    )

    assert [chunk["chunk_index"] for chunk in selected] == [1, 2, 3]


def test_scroll_source_chunks_uses_source_filter_and_paginates():
    module = load_module()
    payloads = []

    def fake_post(_url, payload, headers=None, timeout=60):
        payloads.append(payload)
        if len(payloads) == 1:
            return {
                "result": {
                    "points": [{"payload": {"kb": "testkb", "source_path": "konzept.md", "chunk_index": 1, "text": "## Phase 1"}}],
                    "next_page_offset": "next",
                }
            }
        return {
            "result": {
                "points": [{"payload": {"kb": "testkb", "source_path": "konzept.md", "chunk_index": 2, "text": "## Phase 2"}}],
                "next_page_offset": None,
            }
        }

    module._post_json = fake_post
    chunks = module._scroll_source_chunks(
        "http://qdrant:6333",
        "testkb",
        ["konzept.md"],
        timeout=60,
    )

    assert [chunk["chunk_index"] for chunk in chunks] == [1, 2]
    assert payloads[0]["filter"]["should"][0]["match"]["value"] == "konzept.md"
    assert payloads[1]["offset"] == "next"

def _source_chunk(index, text=None, score=0.0):
    return {
        "collection": "wissen",
        "source_path": "anleitung.md",
        "chunk_index": index,
        "score": score,
        "text": text if text is not None else f"Abschnitt {index} " + (str(index) * 80),
    }


def test_broad_query_expands_forward_across_document_budget():
    module = load_module()
    source = [_source_chunk(index) for index in range(8)]
    selected = module._expand_source_context(
        source,
        [_source_chunk(0, score=0.71)],
        max_chunks=6,
        max_chars=12000,
        neighbor_radius=1,
        broad=module._is_broad_query("Wie genau arbeite ich im Teiledienst?"),
    )

    assert [chunk["chunk_index"] for chunk in selected] == [0, 1, 2, 3, 4, 5]
    assert all(chunk.get("match_type") == "neighbor" for chunk in selected[1:])


def test_specific_query_adds_immediate_neighbours_only():
    module = load_module()
    source = [_source_chunk(index) for index in range(8)]
    selected = module._expand_source_context(
        source,
        [_source_chunk(3, score=0.77)],
        max_chunks=6,
        max_chars=12000,
        neighbor_radius=1,
        broad=False,
    )

    assert [chunk["chunk_index"] for chunk in selected] == [2, 3, 4]


def test_context_budget_keeps_whole_chunks():
    module = load_module()
    source = [_source_chunk(index, text=str(index) * 100) for index in range(5)]
    selected = module._expand_source_context(
        source,
        [_source_chunk(0, text="0" * 100, score=0.8)],
        max_chunks=6,
        max_chars=250,
        broad=True,
    )

    assert [chunk["chunk_index"] for chunk in selected] == [0, 1]
    assert all(len(chunk["text"]) == 100 for chunk in selected)


def test_adjacent_chunk_overlap_is_removed_from_context():
    module = load_module()
    overlap = "gemeinsamer ueberlappender Kontext " * 3
    chunks = [
        _source_chunk(0, text="Erster Teil. " + overlap, score=0.8),
        _source_chunk(1, text=overlap + "Zweiter Teil.", score=0.0),
    ]
    chunks[1]["match_type"] = "neighbor"

    context = module._build_context(chunks)

    assert context.count("gemeinsamer ueberlappender Kontext") == 3
    assert "Erster Teil." in context
    assert "Zweiter Teil." in context

def test_exhaustive_query_loads_complete_document_when_it_fits():
    module = load_module()
    source = [_source_chunk(index, text=str(index) * 100) for index in range(5)]
    query = "Was muss nach unserer KI-Richtlinie alles schriftlich erlaubt werden?"

    selected = module._expand_source_context(
        source,
        [_source_chunk(2, text="2" * 100, score=0.81)],
        max_chunks=6,
        max_chars=12000,
        neighbor_radius=1,
        broad=True,
        exhaustive=module._is_exhaustive_query(query),
    )

    assert module._is_exhaustive_query(query) is True
    assert [chunk["chunk_index"] for chunk in selected] == [0, 1, 2, 3, 4]


def test_exhaustive_query_still_respects_hard_limits():
    module = load_module()
    source = [_source_chunk(index, text=str(index) * 100) for index in range(8)]
    selected = module._expand_source_context(
        source,
        [_source_chunk(2, text="2" * 100, score=0.81)],
        max_chunks=6,
        max_chars=12000,
        broad=True,
        exhaustive=True,
    )

    assert len(selected) == 6
    assert len(selected) < len(source)

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
    test_dynamic_collection_discovery_merges_configured_and_filesystem_bases()
    test_prefer_top_source_keeps_recovery_chunks_and_drops_unrelated_tail()
    test_exact_identifier_routes_to_matching_source_only()
    test_source_filter_is_sent_to_qdrant()
    test_followup_query_keeps_prior_product_identifier()
    test_enumeration_retrieval_collects_distributed_numbered_headings()
    test_enumeration_retrieval_is_generic_for_phases()
    test_scroll_source_chunks_uses_source_filter_and_paginates()
    test_broad_query_expands_forward_across_document_budget()
    test_specific_query_adds_immediate_neighbours_only()
    test_context_budget_keeps_whole_chunks()
    test_adjacent_chunk_overlap_is_removed_from_context()
    test_exhaustive_query_loads_complete_document_when_it_fits()
    test_exhaustive_query_still_respects_hard_limits()
    test_raw_mail_query_is_rejected_before_embedding()
    test_raw_mail_without_signoff_is_rejected_before_embedding()
    test_answer_mail_command_with_raw_mail_is_rejected_before_embedding()
    test_compact_internal_question_is_not_rejected_as_raw_mail()
    print("rag chat direct qdrant tests passed")
