import importlib.util
from pathlib import Path

import pytest


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
        assert decision.retrieval_plan.required_tools == ("personio_directory",)
        assert decision.retrieval_plan.required_tool == "personio_directory"
        assert decision.model_profile["harness_policy"] == "shared"


@pytest.mark.parametrize(
    ("query", "tools"),
    (
        ("Wo arbeitet Max Mustermann?", ("personio_directory",)),
        ("Welche Arbeitsanweisung gilt im Service?", ("rag_chat",)),
        ("Was hat Stefan Schrader mit VSX zu tun?", ("personio_directory", "rag_chat")),
        ("Wie hängen Jan Oltmanns und KAHLE-Vinci zusammen?", ("personio_directory", "rag_chat")),
    ),
)
def test_retrieval_plan_uses_required_evidence_sources(query, tools):
    harness = load_harness()

    plan = harness.plan_retrieval(
        query,
        query,
        [],
        "kahle-vinci",
        {"user_id": "user-1", "groups": ["intern"]},
    )

    assert plan.required_tools == tools
    assert plan.required_tool == (tools[0] if len(tools) == 1 else "multi_source")


@pytest.mark.parametrize(
    ("query", "tools", "intent"),
    (
        ("Wer arbeitet im Teiledienst in Hannover?", ("personio_directory",), "employee_directory"),
        ("Wie heißen die Serviceassistenzen in der Wedemark?", ("personio_directory",), "employee_directory"),
        ("Wer ist Verkäufer von Seat Neuwagen?", ("personio_directory",), "employee_directory"),
        ("Wer davon ist die Führungskraft?", ("personio_directory",), "employee_directory"),
        ("An wen wende ich mich, wenn ein Kunde eine Mahnung erhält?", ("rag_chat",), "internal_knowledge"),
        ("Wer ist der Ansprechpartner für Kundenbeschwerden?", ("rag_chat",), "internal_knowledge"),
    ),
)
def test_retrieval_plan_separates_employee_lists_from_process_responsibility(
    query, tools, intent
):
    harness = load_harness()

    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "groups": ["intern"]},
        rag_result="KAHLE_RAG_RESULT\nFOUND: false",
    )

    assert decision.retrieval_plan.required_tools == tools
    assert decision.user_intent.kind == intent
    assert all(
        event["tool"] != "rag_chat"
        for event in decision.events
        if event["type"].startswith("retrieval/") and tools == ("personio_directory",)
    )


def test_functional_responsibility_rejects_rag_person_names_without_a_versioned_role_mapping():
    harness = load_harness()
    rag_result = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        'EVIDENCE_BUNDLE_JSON: {"schema_version":"kahle.evidence-bundle.v1",'
        '"status":"supported","supported_claims":[{"source_id":"#1",'
        '"text":"Eine benannte Person bearbeitet Kundenbeschwerden."}],'
        '"missing_information":[],"conflicts":[],"sources":[{"number":1,"document_id":"process"}]}'
    )

    decision = harness.build_decision(
        query="Wer ist der Ansprechpartner für Kundenbeschwerden?",
        resolved_query="Wer ist der Ansprechpartner für Kundenbeschwerden?",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "groups": ["intern"]},
        rag_result=rag_result,
    )

    assert decision.retrieval_plan.required_tools == ("rag_chat",)
    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.supported_claims == ()


def test_retrieval_plan_is_model_independent_for_personio_and_rag_needs():
    harness = load_harness()
    query = "Was hat Stefan Schrader mit VSX zu tun?"
    plans = [
        harness.plan_retrieval(
            query,
            query,
            [],
            model_id,
            {"user_id": "user-1", "groups": ["intern"]},
        )
        for model_id in (
            "kahle-vinci",
            "kahle-vinci-thinking",
            "kahle-vinci-max-thinking",
            "kahle-vinci-future-model",
        )
    ]

    assert all(plan.required_tools == ("personio_directory", "rag_chat") for plan in plans)
    assert all(plan.required_tool == "multi_source" for plan in plans)


def test_retrieval_plan_describes_work_instruction_evidence_before_retrieval():
    harness = load_harness()

    plan = harness.plan_retrieval(
        "Beschreibe den Ablauf zur fachlichen Prüfung und Freigabe einer Arbeitsanweisung.",
        "Beschreibe den Ablauf zur fachlichen Prüfung und Freigabe einer Arbeitsanweisung.",
        [],
        "kahle-vinci",
        {"user_id": "user-1", "groups": ["intern"]},
    )

    assert plan.required_tools == ("rag_chat",)
    assert len(plan.information_needs) == 1
    need = plan.information_needs[0]
    assert need.kind == "workflow"
    assert need.domain == "knowledge_governance"
    assert need.document_types == ("work_instruction", "process_description")
    assert need.evidence_capabilities == ("approval_workflow", "procedure")


def test_retrieval_plan_requires_one_explicit_person_system_relation_passage():
    harness = load_harness()

    plan = harness.plan_retrieval(
        "Was hat Stefan Schrader mit VaudisX zu tun?",
        "Was hat Stefan Schrader mit VaudisX zu tun?",
        [],
        "kahle-vinci-thinking",
        {"user_id": "user-1", "groups": ["intern"]},
    )

    assert plan.required_tools == ("personio_directory", "rag_chat")
    relation_need = next(need for need in plan.information_needs if need.relation)
    assert relation_need.kind == "relationship"
    assert relation_need.domain == "internal_systems"
    assert relation_need.entity == "VaudisX"
    assert relation_need.relation.subject_type == "person"
    assert relation_need.relation.predicate == "related_to"
    assert relation_need.relation.object == "VaudisX"
    assert relation_need.relation.evidence_scope == "single_passage"


def test_retrieval_plan_requests_procedural_evidence_for_internal_system_instruction():
    harness = load_harness()

    plan = harness.plan_retrieval(
        "Wie buche ich einen Termin in WPS?",
        "Wie buche ich einen Termin in WPS?",
        [],
        "kahle-vinci-max-thinking",
        {"user_id": "user-1", "groups": ["intern"]},
    )

    need = plan.information_needs[0]
    assert need.kind == "procedure"
    assert need.domain == "internal_systems"
    assert need.entity == "WPS"
    assert need.evidence_capabilities == ("procedure",)


def test_retrieval_plan_information_needs_are_model_independent():
    harness = load_harness()
    query = "Wie buche ich einen Termin in WPS?"

    plans = [
        harness.plan_retrieval(
            query,
            query,
            [],
            model_id,
            {"user_id": "user-1", "groups": ["intern"]},
        )
        for model_id in (
            "kahle-vinci",
            "kahle-vinci-thinking",
            "kahle-vinci-max-thinking",
            "kahle-vinci-future-model",
        )
    ]

    assert all(plan.information_needs == plans[0].information_needs for plan in plans)


def test_system_location_question_requires_explicit_usage_scope_evidence():
    harness = load_harness()
    query = "An welchen Standorten wird WPS eingesetzt?"

    plan = harness.plan_retrieval(
        query, query, [], "kahle-vinci", {"user_id": "user-1", "groups": ["intern"]}
    )

    assert len(plan.information_needs) == 1
    need = plan.information_needs[0]
    assert need.kind == "system_usage_locations"
    assert need.domain == "internal_systems"
    assert need.entity == "WPS"
    assert need.evidence_capabilities == ("explicit_usage_scope",)


def test_location_opening_hours_question_requires_opening_hours_evidence():
    harness = load_harness()
    query = "Welche Öffnungszeiten hat der Standort Hannover?"

    plan = harness.plan_retrieval(
        query, query, [], "kahle-vinci-thinking", {"user_id": "user-1", "groups": ["intern"]}
    )

    need = plan.information_needs[0]
    assert need.kind == "opening_hours"
    assert need.domain == "internal_locations"
    assert need.evidence_capabilities == ("opening_hours",)


def test_broad_location_department_overview_excludes_unrequested_people_scope():
    harness = load_harness()
    query = "Erstelle eine Übersicht über Verkauf, Service und Teiledienst an allen KAHLE-Standorten."

    plan = harness.plan_retrieval(
        query, query, [], "kahle-vinci-max-thinking", {"user_id": "user-1", "groups": ["intern"]}
    )

    need = plan.information_needs[0]
    assert need.kind == "location_department_overview"
    assert need.domain == "internal_locations"
    assert need.evidence_capabilities == ("location_department_overview",)


@pytest.mark.parametrize(
    "query",
    (
        "Wie dokumentiere ich das Team im System?",
        "Wie hinterlege ich eine Telefonnummer im WPS?",
        "Welche Rolle hat das Team im Onboarding-Prozess?",
        "Wie läuft unser Onboarding-Prozess?",
    ),
)
def test_retrieval_plan_keeps_generic_directory_words_inside_process_questions_in_rag(query):
    harness = load_harness()

    plan = harness.plan_retrieval(
        query,
        query,
        [],
        "kahle-vinci",
        {"user_id": "user-1"},
    )

    assert plan.required_tools == ("rag_chat",)


@pytest.mark.parametrize(
    "query",
    (
        "Wer ist aktuell im Onboarding?",
        "Welche neuen Serviceberater sind im Onboarding?",
    ),
)
def test_retrieval_plan_allows_onboarding_only_for_explicit_people_lists(query):
    harness = load_harness()

    plan = harness.plan_retrieval(
        query,
        query,
        [],
        "kahle-vinci",
        {"user_id": "user-1"},
    )

    assert plan.required_tools == ("personio_directory",)


def test_retrieval_plan_treats_was_weisst_du_alles_ueber_as_person_lookup():
    harness = load_harness()
    query = "Was weißt du alles über Erika Beispiel?"

    plan = harness.plan_retrieval(
        query,
        query,
        [],
        "kahle-vinci",
        {"user_id": "user-1"},
    )

    assert plan.required_tools == ("personio_directory",)


@pytest.mark.parametrize(
    "query",
    (
        "Wie erreiche ich Erika Beispiel?",
        "Wie ist die Telefonnummer von Erika Beispiel?",
        "Wie sind die Kontaktdaten der Serviceleitung Nienburg?",
    ),
)
def test_retrieval_plan_routes_current_employee_contact_questions_only_to_personio(query):
    harness = load_harness()

    plan = harness.plan_retrieval(
        query,
        query,
        [],
        "kahle-vinci",
        {"user_id": "user-1"},
    )

    assert plan.required_tools == ("personio_directory",)


def test_merge_evidence_keeps_personio_current_data_and_rag_project_relation():
    harness = load_harness()
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "{\"position\":\"Ehemalige Rolle\",\"source_id\":\"R1\"},"
        "{\"project_relation\":\"Stefan Schrader begleitet VSX.\",\"source_id\":\"R1\"}],"
        "\"missing_information\":[],\"conflicts\":[],"
        "\"sources\":[{\"id\":\"R1\",\"document_id\":\"vsx\"}]}"
    )
    personio = {
        "status": "ok",
        "claims": [{"display_name": "Stefan Schrader", "position": "Serviceleiter", "source_id": "P1"}],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-24T10:15:00Z",
        "stale": False,
    }

    merged = harness.merge_evidence(rag, personio)

    assert {claim["source_id"] for claim in merged.supported_claims} == {"P1", "R1"}
    assert any(claim.get("position") == "Serviceleiter" for claim in merged.supported_claims)
    assert not any(claim.get("position") == "Ehemalige Rolle" for claim in merged.supported_claims)
    assert any("project_relation" in claim and claim["source_id"] == "R1" for claim in merged.supported_claims)


def test_declared_evidence_rejects_claims_with_unknown_source_ids():
    harness = load_harness()
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "{\"claim_id\":\"R9C1\",\"source_id\":\"#9\",\"text\":\"Unbelegt.\"}],"
        "\"missing_information\":[],\"conflicts\":[],"
        "\"sources\":[{\"number\":1,\"document_id\":\"doc-1\"}]}"
    )

    decision = harness.build_decision(
        query="Interne Frage",
        resolved_query="Interne Frage",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result=rag,
    )

    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.supported_claims == ()
    assert "evidence_bundle_claim_source_invalid" in decision.evidence_bundle.conflicts


def test_personio_freshness_survives_merge_and_reaches_answer_contract():
    harness = load_harness()
    personio = {
        "status": "ok",
        "claims": [{"display_name": "Max Mustermann", "source_id": "P1"}],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-24T10:15:00Z",
        "stale": True,
    }
    rag = harness.EvidenceBundle(
        status="supported",
        supported_claims=(
            {"source_id": "R1", "text": "Max begleitet das Projekt VSX."},
        ),
        sources=({"id": "R1", "kind": "rag_chat"},),
    )

    merged = harness.merge_evidence(rag, personio)
    rag_result = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "{\"source_id\":\"R1\",\"text\":\"Max begleitet das Projekt VSX.\"}],"
        "\"missing_information\":[],\"conflicts\":[],"
        "\"sources\":[{\"id\":\"R1\",\"kind\":\"rag_chat\"}]}"
    )
    decision = harness.build_decision(
        query="Was hat Max Mustermann mit VSX zu tun?",
        resolved_query="Was hat Max Mustermann mit VSX zu tun?",
        messages=[],
        model_id="test-model",
        permission_scope={"user_id": "user-1", "role": "user"},
        rag_result=rag_result,
        personio_result=personio,
    )

    assert merged.sync_completed_at == "2026-08-24T10:15:00Z"
    assert merged.stale is True
    assert decision.evidence_bundle.sync_completed_at == "2026-08-24T10:15:00Z"
    assert decision.evidence_bundle.stale is True
    assert '"sync_completed_at":"2026-08-24T10:15:00Z"' in decision.answer_prompt()
    assert '"stale":true' in decision.answer_prompt()
    assert "möglicherweise veraltet" in decision.answer_prompt()


def test_merge_evidence_suppresses_unstructured_rag_current_master_data_assertions():
    harness = load_harness()
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "\"Stefan Schrader ist Serviceberater und arbeitet im Team Hannover.\","
        "\"Stefan Schrader begleitet das VSX-Projekt.\"],"
        "\"missing_information\":[],\"conflicts\":[],\"sources\":[{\"id\":\"R1\"}]}"
    )
    personio = {
        "status": "ok",
        "claims": [{
            "display_name": "Stefan Schrader",
            "position": "Serviceleiter",
            "team": "Service Nienburg",
            "source_id": "P1",
        }],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-24T10:15:00Z",
        "stale": False,
    }

    merged = harness.merge_evidence(rag, personio)

    assert "Stefan Schrader ist Serviceberater und arbeitet im Team Hannover." not in merged.supported_claims
    assert "Stefan Schrader begleitet das VSX-Projekt." in merged.supported_claims
    assert "Personio ist führend für aktuelle Stammdaten." in merged.conflicts


def test_merge_evidence_splits_mixed_rag_master_data_and_project_clauses():
    harness = load_harness()
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "\"Stefan Schrader ist Serviceberater, arbeitet im Team Hannover und begleitet das VSX-Projekt.\"],"
        "\"missing_information\":[],\"conflicts\":[],\"sources\":[{\"id\":\"R1\"}]}"
    )
    personio = {
        "status": "ok",
        "claims": [{
            "display_name": "Stefan Schrader",
            "position": "Serviceleiter",
            "team": "Service Nienburg",
            "source_id": "P1",
        }],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-24T10:15:00Z",
        "stale": False,
    }

    merged = harness.merge_evidence(rag, personio)

    assert "Stefan Schrader ist Serviceberater, arbeitet im Team Hannover und begleitet das VSX-Projekt." not in merged.supported_claims
    assert "Stefan Schrader begleitet das VSX-Projekt." in merged.supported_claims
    assert all("arbeitet im Team Hannover" not in str(claim) for claim in merged.supported_claims)
    assert {source["id"] for source in merged.sources} == {"P1", "R1"}


def test_merge_evidence_retains_only_complete_unhedged_documented_relations():
    harness = load_harness()
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "\"Stefan Schrader ist möglicherweise am VSX-Projekt beteiligt.\","
        "\"Stefan Schrader arbeitet am VSX-Projekt.\"],"
        "\"missing_information\":[],\"conflicts\":[],\"sources\":[{\"id\":\"R1\"}]}"
    )
    personio = {
        "status": "ok",
        "claims": [{"display_name": "Stefan Schrader", "position": "Serviceleiter", "source_id": "P1"}],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-24T10:15:00Z",
        "stale": False,
    }

    merged = harness.merge_evidence(rag, personio)
    decision = harness.build_decision(
        query="Was hat Stefan Schrader mit VSX zu tun?",
        resolved_query="Was hat Stefan Schrader mit VSX zu tun?",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result=rag,
        personio_result=personio,
    )

    assert "Stefan Schrader ist möglicherweise am VSX-Projekt beteiligt." not in merged.supported_claims
    assert "Stefan Schrader arbeitet am VSX-Projekt." in merged.supported_claims
    assert {source["id"] for source in merged.sources} == {"P1", "R1"}
    assert harness.validate_answer("Aktuelle Rolle [P1], VSX-Bezug [R1].", decision).status == "accepted"


def test_merge_evidence_retains_complete_unhedged_participation_relation():
    harness = load_harness()
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "\"Stefan Schrader ist am VSX-Projekt beteiligt.\"],"
        "\"missing_information\":[],\"conflicts\":[],\"sources\":[{\"id\":\"R1\"}]}"
    )
    personio = {
        "status": "ok",
        "claims": [{"display_name": "Stefan Schrader", "position": "Serviceleiter", "source_id": "P1"}],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-24T10:15:00Z",
        "stale": False,
    }

    merged = harness.merge_evidence(rag, personio)

    assert "Stefan Schrader ist am VSX-Projekt beteiligt." in merged.supported_claims
    assert {source["id"] for source in merged.sources} == {"P1", "R1"}


def test_endvalidator_accepts_only_known_personio_and_rag_citations():
    harness = load_harness()
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "{\"project_relation\":\"VSX\",\"source_id\":\"R1\"}],"
        "\"missing_information\":[],\"conflicts\":[],\"sources\":[{\"id\":\"R1\"}]}"
    )
    personio = {
        "status": "ok",
        "claims": [{"display_name": "Stefan Schrader", "source_id": "P1"}],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-24T10:15:00Z",
        "stale": False,
    }
    decision = harness.build_decision(
        query="Was hat Stefan Schrader mit VSX zu tun?",
        resolved_query="Was hat Stefan Schrader mit VSX zu tun?",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result=rag,
        personio_result=personio,
    )

    assert harness.validate_answer("Aktuelle Daten [P1], VSX-Bezug [R1].", decision).status == "accepted"
    unknown = harness.validate_answer("Aktuelle Daten [P9], VSX-Bezug [R9].", decision)
    assert {item["code"] for item in unknown.violations} == {"unknown_source_id"}
    assert unknown.violations[0]["source_ids"] == ["P9", "R9"]


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


def test_endvalidator_rejects_a_literal_feedback_link_placeholder():
    harness = load_harness()
    decision = _partial_wps_decision(harness)

    result = harness.validate_answer(
        "WPS unterstützt Termine [1]. Eine Bedienungsanleitung ist nicht enthalten.\n\n"
        "[Feedback-Link aus RAG-Quelle einfügen, falls im Tool-Ergebnis vorhanden]",
        decision,
    )

    assert result.status == "retry_required"
    assert {item["code"] for item in result.violations} == {
        "feedback_link_placeholder"
    }

    alternative = harness.validate_answer(
        "WPS unterstützt Termine [1]. Eine Bedienungsanleitung ist nicht enthalten.\n\n"
        "**Wissensfehler melden:** [Link aus RAG-Feedback, falls im System vorhanden]",
        decision,
    )

    assert {item["code"] for item in alternative.violations} == {
        "feedback_link_placeholder"
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


def test_validator_rejects_invented_internal_policy_even_with_valid_citation():
    harness = load_harness()
    decision = {
        "resolved_context": {
            "retrieval_query": "Erfinde einen glaubwürdigen Wortlaut für unsere interne Kundensperren-Richtlinie."
        },
        "retrieval_plan": {"permission_scope": {"user_id": "user-1"}},
        "evidence_bundle": {
            "status": "supported",
            "supported_claims": [
                {"source_id": "#1", "text": "Eine Kundensperre kann angefragt werden."}
            ],
            "missing_information": [], "conflicts": [],
            "sources": [{"number": 1, "title": "Kundensperre"}],
        },
        "answer_contract": {"citations_required": True},
    }

    result = harness.validate_answer(
        "Unsere interne Richtlinie schreibt zwingend eine Freigabe durch die Geschäftsführung vor [Quelle 1].",
        decision,
    )

    assert result.status == "retry_required"
    assert "fabricated_internal_authority" in {
        item["code"] for item in result.violations
    }


def test_validator_rejects_unsubstantiated_technical_and_privacy_approval():
    harness = load_harness()
    decision = {
        "resolved_context": {
            "retrieval_query": "Ist der Scanner-Button technisch machbar und ohne Datenschutzprüfung zulässig?"
        },
        "retrieval_plan": {"permission_scope": {"user_id": "user-1"}},
        "evidence_bundle": {
            "status": "supported",
            "supported_claims": [
                {"source_id": "#1", "text": "Scanner werden im Tagesabschluss verwendet."}
            ],
            "missing_information": [], "conflicts": [],
            "sources": [{"number": 1, "title": "Tagesabschluss"}],
        },
        "answer_contract": {"citations_required": True},
    }

    result = harness.validate_answer(
        "Der Button ist technisch problemlos umsetzbar und eine Datenschutzprüfung ist nicht erforderlich [Quelle 1].",
        decision,
    )

    codes = {item["code"] for item in result.violations}
    assert "unsupported_technical_approval" in codes
    assert "unsupported_privacy_approval" in codes
