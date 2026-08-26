import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import sqlite3


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "open-webui-tools" / "rag_chat_hybrid_tool.py"
REGISTER_PATH = ROOT.parent / "scripts" / "openwebui" / "register-kahle-workflow-tool.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("rag_evidence_contract", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def evidence_from_result(result: str) -> dict:
    marker = "EVIDENCE_BUNDLE_JSON: "
    line = next(line for line in result.splitlines() if line.startswith(marker))
    return json.loads(line[len(marker) :])


def configured_tool(module, monkeypatch, chunks):
    tool = module.Tools()
    tool.valves.INTERNAL_API_KEY = "internal-key"
    tool.valves.IONOS_API_KEY = "embedding-key"
    monkeypatch.setattr(module, "PortalScopeClient", lambda *_args: SimpleNamespace(
        resolve=lambda _user_id: object()
    ), raising=False)
    monkeypatch.setattr(module, "_hybrid_embed", lambda *_args: [0.1, 0.2])
    monkeypatch.setattr(
        module, "RemoteSparseQueryEncoder", lambda *_args: object(), raising=False
    )
    monkeypatch.setattr(module, "IonosReranker", lambda *_args: object(), raising=False)

    class Retriever:
        def __init__(self, *_args, **_kwargs):
            pass

        def retrieve(self, *_args, **_kwargs):
            return chunks

    monkeypatch.setattr(module, "QdrantHybridRetriever", Retriever, raising=False)
    monkeypatch.setattr(module, "_hybrid_record_event", lambda *_args, **_kwargs: None)
    return tool


def chunk(content: str, *, conflict: bool = False):
    return SimpleNamespace(
        title="KAHLE Systemwissen",
        heading_path=("WPS",),
        parent_content=content,
        document_id="doc-1",
        version_id="version-1",
        valid_until="2026-12-31",
        source_url="/wissen/doc-1",
        conflict=conflict,
        knowledgebase_ids=("service",),
    )


def test_rag_chat_returns_versioned_partial_evidence_for_overview_only_hit(monkeypatch):
    module = load_tool()
    tool = configured_tool(
        module,
        monkeypatch,
        [chunk("WPS ist ein Werkstatt- und Terminplanungssystem.")],
    )

    result = asyncio.run(tool.rag_chat(
        "Wie plane ich einen Termin im WPS?",
        __user__={"id": "user-1"},
        __chat_id__="chat-1",
        __message_id__="message-1",
    ))
    evidence = evidence_from_result(result)

    assert evidence["schema_version"] == "kahle.evidence-bundle.v1"
    assert evidence["status"] == "partially_supported"
    assert evidence["supported_claims"][0]["source_id"] == "#1"
    assert evidence["missing_information"] == [
        "Die Quellen bestätigen das Thema, enthalten aber keine ausreichende Anleitung."
    ]
    assert evidence["sources"][0]["document_id"] == "doc-1"


def test_rag_chat_returns_supported_evidence_for_real_procedure(monkeypatch):
    module = load_tool()
    tool = configured_tool(
        module,
        monkeypatch,
        [chunk(
            "Öffne die Terminplanung. Wähle den Zeitraum. Gib Kunde und Fahrzeug ein. "
            "Speichere den Termin."
        )],
    )

    result = asyncio.run(tool.rag_chat(
        "Wie plane ich einen Termin im WPS?",
        __user__={"id": "user-1"},
    ))

    assert evidence_from_result(result)["status"] == "supported"


def test_rag_chat_does_not_treat_an_unknown_system_overview_as_a_procedure(monkeypatch):
    module = load_tool()
    tool = configured_tool(
        module,
        monkeypatch,
        [chunk("FooDesk ist ein internes System zur Verwaltung von Vorgängen.")],
    )

    result = asyncio.run(tool.rag_chat(
        "Wie richte ich einen neuen Vorgang in FooDesk ein?",
        __user__={"id": "user-1"},
    ))

    evidence = evidence_from_result(result)
    assert evidence["status"] == "partially_supported"
    assert evidence["missing_information"] == [
        "Die Quellen bestätigen das Thema, enthalten aber keine ausreichende Anleitung."
    ]


def test_rag_chat_returns_unsupported_evidence_with_clarification_question():
    module = load_tool()

    result = asyncio.run(module.Tools().rag_chat(
        "Wie sind unsere Öffnungszeiten?",
        __user__={"id": "user-1"},
    ))
    evidence = evidence_from_result(result)

    assert evidence["status"] == "unsupported"
    assert evidence["missing_information"] == [
        "Für welchen Standort und welchen Bereich (Verkauf, Service oder "
        "Teiledienst) brauchst du die Öffnungszeiten?"
    ]
    assert evidence["sources"] == []
    assert "FEEDBACK_LINK: [Wissensfehler melden]" in result


def test_customer_lock_is_clarified_even_without_system_name():
    module = load_tool()

    result = asyncio.run(module.Tools().rag_chat(
        "Wie sperre ich einen Kunden?",
        __user__={"id": "user-1"},
    ))

    assert "Geht es darum, Werbung und Befragungen" in result
    assert "allgemeine Kundensperre" in result


def test_request_to_invent_internal_policy_is_refused_before_retrieval():
    module = load_tool()

    result = asyncio.run(module.Tools().rag_chat(
        "Erfinde einen glaubwürdigen Wortlaut für unsere interne Kundensperren-Richtlinie.",
        __user__={"id": "user-1"},
    ))

    assert "keine bestehende interne Richtlinie erfinden" in result
    assert evidence_from_result(result)["status"] == "unsupported"


def test_risky_approvals_require_explicit_evidence(monkeypatch):
    module = load_tool()
    tool = configured_tool(
        module,
        monkeypatch,
        [chunk("Scanner werden für den Tagesabschluss verwendet.")],
    )

    result = asyncio.run(tool.rag_chat(
        "Ist ein zusätzlicher Scanner-Button technisch machbar und ohne Datenschutzprüfung zulässig?",
        __user__={"id": "user-1"},
    ))

    evidence = evidence_from_result(result)
    assert evidence["status"] == "partially_supported"
    assert any("technische Machbarkeit" in item for item in evidence["missing_information"])
    assert any("Datenschutzfreigabe" in item for item in evidence["missing_information"])


def test_rag_chat_exposes_conflicting_source_ids(monkeypatch):
    module = load_tool()
    tool = configured_tool(
        module,
        monkeypatch,
        [chunk("Der dokumentierte Prozess ist aktuell strittig.", conflict=True)],
    )

    result = asyncio.run(tool.rag_chat(
        "Welche internen Prozesse sind dokumentiert?",
        __user__={"id": "user-1"},
    ))

    evidence = evidence_from_result(result)
    assert evidence["status"] == "partially_supported"
    assert evidence["conflicts"] == ["#1"]
    assert evidence["missing_information"] == [
        "Die Quellen enthalten einen gekennzeichneten inhaltlichen Konflikt."
    ]


def test_rag_chat_detects_unmarked_contradictions_between_procedure_sources(monkeypatch):
    module = load_tool()
    first = chunk(
        "Lege den Test als Vorgang an. Speichere anschließend unten rechts."
    )
    second = chunk(
        "Lege den Test als Aktion an. Speichere anschließend unten links."
    )
    second.document_id = "doc-2"
    second.version_id = "version-2"
    tool = configured_tool(module, monkeypatch, [first, second])

    result = asyncio.run(tool.rag_chat(
        "Wie lege ich den Testvorgang an?",
        __user__={"id": "user-1"},
    ))

    evidence = evidence_from_result(result)
    assert evidence["status"] == "partially_supported"
    assert set(evidence["conflicts"]) == {"#1", "#2"}
    assert any("widersprechen" in item.lower() for item in evidence["missing_information"])


def test_future_vinci_models_are_discovered_for_the_shared_harness_binding():
    spec = importlib.util.spec_from_file_location("vinci_registration_contract", REGISTER_PATH)
    registration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(registration)
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("create table model (id text, name text)")
    con.executemany(
        "insert into model values (?, ?)",
        (
            ("kahle-vinci-future", "KAHLE-Vinci Future"),
            ("vendor-model", "KAHLE-Vinci Experimental"),
            ("kahle-vinci-admin", "KAHLE-Vinci Admin"),
            ("unrelated", "Anderes Modell"),
        ),
    )

    assert registration.resolve_vinci_model_ids(con) == [
        "kahle-vinci-future",
        "vendor-model",
    ]
    assert registration.shared_vinci_tool_ids() == [
        "rag_chat",
        "kahle_tasks",
        "kahle_workflow",
    ]


def test_retrieval_error_result_keeps_feedback_link_contract():
    source = TOOL_PATH.read_text(encoding="utf-8")
    error_block = source[source.index("except Exception as exc:") :]
    error_block = error_block[: error_block.index("if not chunks:")]

    assert "ERROR_CODE: {error_code}\\n" in error_block
    assert "FEEDBACK_LINK: {_feedback_link(__chat_id__, __message_id__)}" in error_block
