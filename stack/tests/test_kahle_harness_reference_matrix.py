from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_reference_harness", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def rag_result(*, status, claims=(), missing=(), sources=(), context=""):
    bundle = {
        "schema_version": "kahle.evidence-bundle.v1",
        "status": status,
        "supported_claims": list(claims),
        "missing_information": list(missing),
        "conflicts": [],
        "sources": list(sources),
    }
    return (
        "KAHLE_RAG_RESULT\n"
        f"FOUND: {'false' if status == 'unsupported' else 'true'}\n"
        f"EVIDENCE_BUNDLE_JSON: {json.dumps(bundle, ensure_ascii=False)}\n"
        f"CONTEXT:\n{context}"
    )


def decision(harness, query, result, *, model="kahle-vinci", user_id="user-1", messages=None):
    return harness.build_decision(
        query=query,
        resolved_query=query,
        messages=messages or [],
        model_id=model,
        permission_scope={"user_id": user_id, "groups": ["intern"]},
        rag_result=result,
    )


def test_reference_matrix_unknown_system_without_and_with_real_instructions():
    harness = load_harness()
    overview = rag_result(
        status="partially_supported",
        claims=({"source_id": "#1", "text": "FooDesk verwaltet Vorgänge."},),
        missing=("Eine Bedienungsanleitung fehlt.",),
        sources=({"number": 1, "document_id": "systems"},),
    )
    instructions = rag_result(
        status="supported",
        claims=({"source_id": "#2", "text": "Öffnen, wählen und speichern."},),
        sources=({"number": 2, "document_id": "foodesk-guide"},),
    )

    partial = decision(harness, "Wie richte ich einen Vorgang in FooDesk ein?", overview)
    supported = decision(harness, "Wie richte ich einen Vorgang in FooDesk ein?", instructions)

    assert harness.validate_answer(
        "FooDesk verwaltet Vorgänge [1]. Eine Bedienungsanleitung ist nicht enthalten.",
        partial,
    ).status == "accepted"
    assert harness.validate_answer(
        "1. Öffne die Terminplanung [2].\n2. Wähle den Termin [2].\n3. Speichere ihn [2].",
        supported,
    ).status == "accepted"


def test_reference_matrix_person_directory_is_ready_for_future_personio_adapter():
    harness = load_harness()
    result = rag_result(
        status="supported",
        claims=({"source_id": "#3", "text": "Thomas Keller ist Geschäftsführer."},),
        sources=({"number": 3, "document_id": "contacts"},),
    )

    for model in (
        "kahle-vinci", "kahle-vinci-thinking", "kahle-vinci-max-thinking",
        "kahle-vinci-future",
    ):
        current = decision(harness, "Wer ist Thomas Keller?", result, model=model)
        assert current.user_intent.kind == "employee_directory"
        assert current.retrieval_plan.required_tool == "rag_chat"
        assert harness.validate_answer(
            "Thomas Keller ist Geschäftsführer [3].", current
        ).status == "accepted"


def test_reference_matrix_aliases_followups_and_clarifications():
    harness = load_harness()
    messages = [
        {"role": "user", "content": "Wie sind unsere Öffnungszeiten?"},
        {"role": "assistant", "content": "Für welchen Standort und Bereich?"},
        {"role": "user", "content": "TD in NIE"},
    ]
    opening = decision(
        harness,
        "TD in NIE",
        rag_result(status="unsupported", missing=("Standort oder Bereich fehlt.",)),
        messages=messages,
    )
    lock = decision(
        harness,
        "Wie sperre ich einen Kunden in Vaudis?",
        (
            "KAHLE_RAG_RESULT\nFOUND: false\nCLARIFICATION_REQUIRED: true\n"
            "ANSWER: Geht es um Werbewiderspruch oder allgemeine Kundensperre?"
        ),
    )

    assert opening.resolved_context.aliases == {"TD": "Teiledienst", "NIE": "Nienburg"}
    assert opening.resolved_context.conversation_reference is True
    assert lock.user_intent.clarification_required is True
    assert lock.direct_answer().startswith("Geht es um Werbewiderspruch")


def test_reference_matrix_permission_scope_and_model_parity_are_data_not_branches():
    harness = load_harness()
    allowed = rag_result(
        status="supported",
        claims=({"source_id": "#4", "text": "Freigegebener Prozess."},),
        sources=({"number": 4, "document_id": "allowed"},),
    )
    denied = rag_result(
        status="unsupported",
        missing=("Keine freigegebene Evidenz im Berechtigungsumfang.",),
    )

    employee = decision(harness, "Welche Prozesse sind dokumentiert?", denied, user_id="employee")
    manager = decision(
        harness, "Welche Prozesse sind dokumentiert?", allowed,
        user_id="manager", model="kahle-vinci-max-thinking",
    )
    future = decision(
        harness, "Welche Prozesse sind dokumentiert?", allowed,
        user_id="manager", model="kahle-vinci-future",
    )

    assert employee.evidence_bundle.status == "unsupported"
    assert manager.evidence_bundle.status == "supported"
    manager_payload = manager.to_dict()
    future_payload = future.to_dict()
    manager_payload.pop("model_profile")
    future_payload.pop("model_profile")
    assert manager_payload == future_payload


def test_reference_matrix_runtime_metrics_contract_is_persisted_by_middleware():
    middleware = (
        ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"
    ).read_text(encoding="utf-8")

    for field in (
        "model_name", "intent_kind", "required_tool", "tool_called", "evidence_status",
        "source_count", "retry_count", "fallback_used", "delivery_status", "latency_ms",
    ):
        assert f"'{field}'" in middleware
    assert "'kahle_harness_metrics': metadata['kahle_harness_metrics']" in middleware
