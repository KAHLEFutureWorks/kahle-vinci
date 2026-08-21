import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = (
    ROOT
    / "open-webui-overrides"
    / "open_webui"
    / "utils"
    / "kahle_knowledge_harness.py"
)


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_knowledge_harness", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_shadow_harness_builds_structured_contract_without_answer_text():
    harness = load_harness()

    decision = harness.build_shadow_decision(
        query="Wie plane ich einen Termin im WPS?",
        resolved_query="Wie plane ich einen Termin im WPS?",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "groups": ["service"]},
        rag_result=(
            "KAHLE_RAG_RESULT\nFOUND: true\nCONTEXT:\n"
            "[Quelle 1] Systemlandkarte\n"
            "WPS ist ein Werkstatt- und Terminplanungssystem.\n"
            "SOURCES_JSON: []"
        ),
    )

    payload = decision.to_dict()
    assert payload["schema_version"] == "kahle.knowledge-harness.v1"
    assert payload["user_intent"]["kind"] == "internal_knowledge"
    assert payload["user_intent"]["procedural"] is True
    assert payload["retrieval_plan"]["required_tool"] == "rag_chat"
    assert payload["retrieval_plan"]["permission_scope"]["user_id"] == "user-1"
    assert payload["evidence_bundle"]["status"] == "partially_supported"
    assert payload["evidence_bundle"]["missing_information"]
    assert payload["answer_contract"]["incomplete_evidence"] == "partial_answer"
    assert payload["answer_contract"]["allow_unsubstantiated_examples"] is False
    assert payload["answer_contract"]["allow_unsubstantiated_referrals"] is False
    assert "Ergänze keine Beispiele" in decision.answer_prompt()
    assert "Support-Verweise" in decision.answer_prompt()
    assert "answer" not in payload


def test_shadow_harness_accepts_real_procedure_and_preserves_sources():
    harness = load_harness()
    rag_result = (
        "KAHLE_RAG_RESULT\nFOUND: true\nCONTEXT:\n"
        "[Quelle 7] WPS-Anleitung\n"
        "Öffne die Terminplanung. Wähle den Zeitraum. Gib Kunde und Fahrzeug ein. "
        "Speichere den Termin.\n"
        'SOURCES_JSON: [{"source_id":"doc-7","title":"WPS-Anleitung"}]'
    )

    decision = harness.build_shadow_decision(
        query="Wie plane ich einen Termin im WPS?",
        resolved_query="Wie plane ich einen Termin im WPS?",
        messages=[],
        model_id="kahle-vinci-thinking",
        permission_scope={"user_id": "user-1"},
        rag_result=rag_result,
    )

    assert decision.evidence_bundle.status == "supported"
    assert decision.evidence_bundle.sources[0]["source_id"] == "doc-7"


def test_shared_harness_requires_procedural_evidence_for_an_unknown_system():
    harness = load_harness()
    query = "Wie richte ich einen neuen Vorgang in FooDesk ein?"
    rag_result = (
        "KAHLE_RAG_RESULT\nFOUND: true\nCONTEXT:\n"
        "[Quelle 3] Systemlandkarte\n"
        "FooDesk ist ein internes System zur Verwaltung von Vorgängen.\n"
        'SOURCES_JSON: [{"source_id":"doc-3","title":"Systemlandkarte"}]'
    )

    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="kahle-vinci-future",
        permission_scope={"user_id": "user-1"},
        rag_result=rag_result,
    )

    assert decision.user_intent.procedural is True
    assert decision.evidence_bundle.status == "partially_supported"
    assert decision.evidence_bundle.missing_information == (
        "Die Evidenz beschreibt das Thema, enthält aber keine ausreichende Anleitung.",
    )


def test_shadow_harness_resolves_documented_aliases_without_blind_rewrite():
    harness = load_harness()

    decision = harness.build_shadow_decision(
        query="Wie sind die Öffnungszeiten bei TD in NIE?",
        resolved_query="Wie sind die Öffnungszeiten beim Teiledienst in Nienburg?",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result="KAHLE_RAG_RESULT\nFOUND: false",
    )

    aliases = decision.resolved_context.aliases
    assert aliases == {"TD": "Teiledienst", "NIE": "Nienburg"}
    assert decision.resolved_context.original_query == (
        "Wie sind die Öffnungszeiten bei TD in NIE?"
    )
    assert decision.resolved_context.retrieval_query.endswith("Nienburg?")


def test_retrieval_alias_resolution_expands_only_documented_whole_tokens():
    module = load_harness()

    assert module.resolve_query_aliases("TD in NIE") == "Teiledienst in Nienburg"
    assert module.resolve_query_aliases("HAN, VK und SHG") == (
        "Hannover, Verkauf und Stadthagen"
    )
    assert module.resolve_query_aliases("Studie und Hinweis") == "Studie und Hinweis"


def test_process_overview_with_explicitly_excluded_steps_is_not_procedural():
    harness = load_harness()
    query = (
        "Welche internen Prozesse sind dokumentiert? Gib mir eine Übersicht, "
        "aber keine unbelegten Ablaufschritte."
    )
    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result="KAHLE_RAG_RESULT\nFOUND: false",
    )

    assert decision.user_intent.procedural is False


def test_shadow_harness_records_followup_context_and_real_ambiguity():
    harness = load_harness()
    messages = [
        {"role": "user", "content": "Wie sind unsere Öffnungszeiten?"},
        {
            "role": "assistant",
            "content": "Für welchen Standort und welchen Bereich brauchst du sie?",
        },
        {"role": "user", "content": "HAN, alles"},
    ]

    followup = harness.build_shadow_decision(
        query="HAN, alles",
        resolved_query="Öffnungszeiten Verkauf Service Teiledienst Hannover",
        messages=messages,
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result="KAHLE_RAG_RESULT\nFOUND: false",
    )
    ambiguous = harness.build_shadow_decision(
        query="Wie sperre ich einen Kunden in Vaudis?",
        resolved_query="Wie sperre ich einen Kunden in Vaudis?",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result=(
            "KAHLE_RAG_RESULT\nFOUND: false\n"
            "CLARIFICATION_REQUIRED: true\n"
            "ANSWER: Geht es um Werbewiderspruch oder allgemeine Kundensperre?"
        ),
    )

    assert followup.resolved_context.conversation_reference is True
    assert followup.resolved_context.aliases["HAN"] == "Hannover"
    assert ambiguous.user_intent.clarification_required is True
    assert ambiguous.user_intent.clarification_question.startswith("Geht es um")


def test_shadow_harness_is_model_invariant_and_emits_native_event_plan():
    harness = load_harness()
    kwargs = {
        "query": "Wer ist Engin Bayir?",
        "resolved_query": "Wer ist Engin Bayir?",
        "messages": [],
        "permission_scope": {"user_id": "user-1", "groups": ["intern"]},
        "rag_result": "KAHLE_RAG_RESULT\nFOUND: false",
    }

    vinci = harness.build_shadow_decision(model_id="kahle-vinci", **kwargs).to_dict()
    thinking = harness.build_shadow_decision(
        model_id="kahle-vinci-thinking", **kwargs
    ).to_dict()

    vinci.pop("model_profile")
    thinking.pop("model_profile")
    assert vinci == thinking
    assert [event["type"] for event in vinci["events"]] == [
        "intent/started",
        "intent/completed",
        "retrieval/started",
        "retrieval/completed",
        "evidence/completed",
    ]
    assert vinci["answer_contract"]["preserve_native_tool_status"] is True
    assert vinci["answer_contract"]["preserve_document_sources"] is True
    assert vinci["answer_contract"]["preserve_feedback_link"] is True


def test_shadow_harness_policy_is_identical_for_max_and_future_models():
    harness = load_harness()
    kwargs = {
        "query": "Wer ist Thomas Keller?",
        "resolved_query": "Wer ist Thomas Keller?",
        "messages": [],
        "permission_scope": {"user_id": "user-1"},
        "rag_result": "KAHLE_RAG_RESULT\nFOUND: false",
    }

    model_ids = (
        "kahle-vinci",
        "kahle-vinci-thinking",
        "kahle-vinci-max-thinking",
        "kahle-vinci-future-model",
    )
    decisions = [
        harness.build_shadow_decision(model_id=model_id, **kwargs).to_dict()
        for model_id in model_ids
    ]
    for decision in decisions:
        decision.pop("model_profile")

    assert decisions[1:] == decisions[:-1]
    assert all(
        harness.build_shadow_decision(model_id=model_id, **kwargs).model_profile[
            "harness_policy"
        ]
        == "shared"
        for model_id in model_ids
    )


def test_person_questions_use_employee_directory_intent_with_current_rag_adapter():
    harness = load_harness()
    for query in (
        "Wer ist Engin Bayir?",
        "Wer ist Thomas Keller?",
        "Wer ist unser Ansprechpartner im Service?",
        "Wie lautet die dienstliche E-Mail von Thomas Keller?",
    ):
        decision = harness.build_decision(
            query=query,
            resolved_query=query,
            messages=[],
            model_id="kahle-vinci-max-thinking",
            permission_scope={"user_id": "user-1"},
            rag_result="KAHLE_RAG_RESULT\nFOUND: false",
        )

        assert decision.user_intent.kind == "employee_directory"
        assert decision.retrieval_plan.required_tool == "rag_chat"
        assert decision.model_profile["harness_policy"] == "shared"


def test_process_question_does_not_enter_employee_directory_intent():
    harness = load_harness()
    decision = harness.build_decision(
        query="Wie läuft die Terminbuchung im WPS?",
        resolved_query="Wie läuft die Terminbuchung im WPS?",
        messages=[],
        model_id="kahle-vinci-future",
        permission_scope={"user_id": "user-1"},
        rag_result="KAHLE_RAG_RESULT\nFOUND: false",
    )

    assert decision.user_intent.kind == "internal_knowledge"


def test_shadow_harness_prefers_tool_evidence_bundle_over_local_inference():
    harness = load_harness()
    evidence = {
        "schema_version": "kahle.evidence-bundle.v1",
        "status": "partially_supported",
        "supported_claims": [{"source_id": "#4", "text": "WPS existiert."}],
        "missing_information": ["Eine Bedienungsanleitung fehlt."],
        "conflicts": [],
        "sources": [{"number": 4, "document_id": "doc-4"}],
    }
    rag_result = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        f"EVIDENCE_BUNDLE_JSON: {__import__('json').dumps(evidence)}\n"
        "CONTEXT:\n[Quelle 4] Systemlandkarte\nWPS existiert."
    )

    decision = harness.build_shadow_decision(
        query="Wie plane ich einen Termin im WPS?",
        resolved_query="Wie plane ich einen Termin im WPS?",
        messages=[],
        model_id="kahle-vinci-max-thinking",
        permission_scope={"user_id": "user-1"},
        rag_result=rag_result,
    )

    assert decision.evidence_bundle.status == "partially_supported"
    assert decision.evidence_bundle.supported_claims[0]["source_id"] == "#4"
    assert decision.evidence_bundle.missing_information == (
        "Eine Bedienungsanleitung fehlt.",
    )


def test_middleware_supports_shadow_and_active_answer_contract_modes():
    middleware = (
        ROOT
        / "open-webui-overrides"
        / "open_webui"
        / "utils"
        / "middleware.py"
    ).read_text(encoding="utf-8")

    assert "build_knowledge_harness_decision(" in middleware
    assert "metadata['kahle_knowledge_harness_shadow']" in middleware
    assert "metadata['kahle_knowledge_harness_active'] = True" in middleware
    assert "harness_decision.answer_prompt()" in middleware
    assert "add_or_update_system_message(" in middleware


def test_answer_prompt_is_model_independent_and_carries_evidence_contract():
    harness = load_harness()
    rag_result = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"partially_supported\","
        "\"supported_claims\":[{\"source_id\":\"#1\",\"text\":\"WPS existiert.\"}],"
        "\"missing_information\":[\"Eine Anleitung fehlt.\"],"
        "\"conflicts\":[],\"sources\":[{\"number\":1}]}"
    )
    prompts = []
    for model_id in (
        "kahle-vinci",
        "kahle-vinci-thinking",
        "kahle-vinci-max-thinking",
        "kahle-vinci-future",
    ):
        decision = harness.build_shadow_decision(
            query="Wie plane ich einen Termin im WPS?",
            resolved_query="Wie plane ich einen Termin im WPS?",
            messages=[],
            model_id=model_id,
            permission_scope={"user_id": "user-1"},
            rag_result=rag_result,
        )
        prompts.append(decision.answer_prompt())

    assert prompts[1:] == prompts[:-1]
    assert "KAHLE_KNOWLEDGE_ANSWER_CONTRACT" in prompts[0]
    assert '"status":"partially_supported"' in prompts[0]
    assert "Eine Anleitung fehlt." in prompts[0]
    assert "Antworte nur aus der bereitgestellten Evidenz" in prompts[0]


def test_unsupported_decision_provides_one_stable_pre_answer_result():
    harness = load_harness()
    decision = harness.build_shadow_decision(
        query="Wie läuft der unbekannte Prozess?",
        resolved_query="Wie läuft der unbekannte Prozess?",
        messages=[],
        model_id="kahle-vinci-max-thinking",
        permission_scope={"user_id": "user-1"},
        rag_result=(
            "KAHLE_RAG_RESULT\nFOUND: false\n"
            "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
            "\"status\":\"unsupported\",\"supported_claims\":[],"
            "\"missing_information\":[\"Keine freigegebene Information.\"],"
            "\"conflicts\":[],\"sources\":[]}"
        ),
    )

    assert decision.direct_answer() == (
        "Dazu habe ich keine verlässliche freigegebene Information."
    )


def _partial_wps_decision(harness, *, user_id="user-1"):
    evidence = {
        "schema_version": "kahle.evidence-bundle.v1",
        "status": "partially_supported",
        "supported_claims": [{"source_id": "#1", "text": "WPS unterstützt Termine."}],
        "missing_information": ["Eine Bedienungsanleitung fehlt."],
        "conflicts": [],
        "sources": [{"number": 1, "document_id": "doc-1"}],
    }
    return harness.build_decision(
        query="Wie buche ich einen Termin in WPS?",
        resolved_query="Wie buche ich einen Termin in WPS?",
        messages=[],
        model_id="kahle-vinci-future",
        permission_scope={"user_id": user_id},
        rag_result=(
            "KAHLE_RAG_RESULT\nFOUND: true\n"
            f"EVIDENCE_BUNDLE_JSON: {__import__('json').dumps(evidence)}"
        ),
    )


def test_endvalidator_accepts_cited_partial_answer_with_disclosed_gap():
    harness = load_harness()
    decision = _partial_wps_decision(harness)

    result = harness.validate_answer(
        "WPS unterstützt die Terminplanung [1]. Eine Bedienungsanleitung ist nicht enthalten.",
        decision,
    )

    assert result.status == "accepted"
    assert result.retry_required is False
    assert result.violations == ()


def test_endvalidator_returns_structured_retry_without_rewriting_answer():
    harness = load_harness()
    decision = _partial_wps_decision(harness)
    original = (
        "WPS unterstützt Termine [1]. Wende dich für die Anleitung an den Support."
    )

    result = harness.validate_answer(original, decision)

    assert result.status == "retry_required"
    assert {item["code"] for item in result.violations} == {
        "missing_information_not_disclosed",
        "unsubstantiated_referral",
    }
    assert original not in result.retry_prompt()
    assert "kahle.answer-retry.v1" in result.retry_prompt()
    assert "unsubstantiated_referral" in result.retry_prompt()


def test_endvalidator_rejects_unknown_source_ids_and_missing_permission_scope():
    harness = load_harness()
    decision = _partial_wps_decision(harness, user_id="")

    result = harness.validate_answer(
        "WPS unterstützt Termine [9]. Eine Bedienungsanleitung ist nicht enthalten.",
        decision,
    )

    assert {item["code"] for item in result.violations} == {
        "permission_scope_missing",
        "unknown_source_id",
    }


def test_endvalidator_rejects_supported_but_unrequested_department_sections():
    harness = load_harness()
    evidence = {
        "schema_version": "kahle.evidence-bundle.v1",
        "status": "supported",
        "supported_claims": [{"source_id": "#1", "text": "Öffnungszeiten Nienburg."}],
        "missing_information": [],
        "conflicts": [],
        "sources": [{"number": 1, "document_id": "loc-nie"}],
    }
    decision = harness.build_decision(
        query="TD in NIE",
        resolved_query="Teiledienst in Nienburg",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result=(
            "KAHLE_RAG_RESULT\nFOUND: true\n"
            f"EVIDENCE_BUNDLE_JSON: {__import__('json').dumps(evidence)}"
        ),
    )

    expanded = harness.validate_answer(
        "- **Verkauf:** 9–18 Uhr\n- **Service:** 7:30–17 Uhr\n"
        "- **Teiledienst:** 7:30–17 Uhr [1]",
        decision,
    )
    focused = harness.validate_answer(
        "Der Teiledienst ist von 7:30 bis 17 Uhr geöffnet [1].",
        decision,
    )

    assert {item["code"] for item in expanded.violations} == {
        "unrequested_scope_expansion"
    }
    assert focused.status == "accepted"


def test_validation_fallback_uses_only_declared_missing_information():
    harness = load_harness()
    decision = _partial_wps_decision(harness)

    assert decision.validation_fallback() == (
        "Die vorhandenen Quellen beantworten nur einen Teil der Anfrage. "
        "Eine Bedienungsanleitung fehlt."
    )


def test_harness_metrics_summary_calculates_rates_and_nearest_rank_percentiles():
    harness = load_harness()
    records = [
        {
            "required_tool": "rag_chat", "tool_called": "rag_chat",
            "final_validation_status": "accepted", "retry_count": 0,
            "fallback_used": False, "source_count": 1,
            "document_sources_present": True, "feedback_link_present": True,
            "latency_ms": 100,
        },
        {
            "required_tool": "rag_chat", "tool_called": "rag_chat",
            "final_validation_status": "accepted", "retry_count": 1,
            "fallback_used": False, "source_count": 1,
            "document_sources_present": True, "feedback_link_present": True,
            "latency_ms": 200,
        },
        {
            "required_tool": "rag_chat", "tool_called": "rag_chat",
            "final_validation_status": "retry_required", "retry_count": 1,
            "fallback_used": True, "source_count": 0,
            "document_sources_present": False, "feedback_link_present": True,
            "latency_ms": 900,
        },
    ]

    summary = harness.summarize_harness_metrics(records)

    assert summary == {
        "schema_version": "kahle.harness-metrics-summary.v1",
        "sample_size": 3,
        "correct_tool_path_rate": 1.0,
        "accepted_rate": 0.6667,
        "retry_rate": 0.6667,
        "fallback_rate": 0.3333,
        "source_presence_rate": 1.0,
        "feedback_link_rate": 1.0,
        "latency_p50_ms": 200,
        "latency_p95_ms": 900,
    }


def test_local_compose_activates_harness_and_mounts_shared_module():
    stack_root = ROOT
    base = (stack_root / "docker-compose.yml").read_text(encoding="utf-8")
    local = (stack_root / "docker-compose.local-edge.yml").read_text(encoding="utf-8")

    assert "kahle_knowledge_harness.py:/app/backend/open_webui/utils/kahle_knowledge_harness.py:ro" in base
    assert 'KAHLE_KNOWLEDGE_HARNESS_MODE: "active"' in local
