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


@pytest.mark.parametrize(
    ("query", "expected_tools"),
    (
        ("Wer ist Erika Beispiel?", ("personio_directory",)),
        ("Wer ist Anna Beispiel?", ("personio_directory",)),
        (
            "Wer ist unser Ansprechpartner im Service?",
            ("personio_directory", "rag_chat"),
        ),
        (
            "Wie lautet die dienstliche E-Mail von Erika Beispiel?",
            ("personio_directory",),
        ),
    ),
)
def test_person_questions_use_employee_directory_intent_with_current_rag_adapter(
    query, expected_tools
):
    harness = load_harness()
    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="kahle-vinci-max-thinking",
        permission_scope={"user_id": "user-1"},
        rag_result="KAHLE_RAG_RESULT\nFOUND: false",
    )

    assert decision.user_intent.kind == "employee_directory"
    assert decision.retrieval_plan.required_tools == expected_tools
    assert decision.retrieval_plan.required_tool == (
        "multi_source" if len(expected_tools) > 1 else expected_tools[0]
    )
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
        "Wer sind die Verkäufer in Nienburg?",
        "Welche Serviceassistentinnen arbeiten in Nienburg?",
        "Wer ist die Führungskraft von Erika Beispiel?",
    ),
)
def test_retrieval_plan_routes_current_employee_role_and_supervisor_questions_to_personio(query):
    harness = load_harness()

    plan = harness.plan_retrieval(
        query,
        query,
        [],
        "kahle-vinci",
        {"user_id": "user-1"},
    )

    assert plan.required_tools == ("personio_directory",)


def test_supervisor_typo_stays_personio_only():
    harness = load_harness()
    query = "Wer ist die Führungskrft von Erika Beispiel?"

    plan = harness.plan_retrieval(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
    )

    assert plan.required_tools == ("personio_directory",)
    assert harness.classify_personio_directory_intent(query) == "supervisor_lookup"


@pytest.mark.parametrize(
    "query",
    (
        "Wer sind die Serviceassistenzen in Nienburg?",
        "Nenne mir die Serviceassistenzen in Nienburg.",
        "Wie heißen die Serviceassistenzen in Nienburg?",
        "Liste mir die Serviceassistenzen in Nienburg auf.",
        "Zeige mir die Verkäufer in Nienburg.",
        "Zeige mir die Mitarbeiter aus dem Verkauf am Standort Hannover.",
        "Nenne mir die Serviceberater in Nienburg.",
        "Wie heißen die Servicekräfte am Standort Nienburg?",
        "Wie heissen die Servicekraefte am Standort Nienburg?",
    ),
)
def test_retrieval_plan_routes_controlled_role_list_wordings_to_personio(query):
    harness = load_harness()

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
        "Bitte gib mir den Kontakt von Erika Beispiel.",
        "Gib mir Infos über Erika Beispiel.",
        "Gib mir Infos ueber Erika Beispiel.",
        "Welche Abteilung hat Erika Beispiel?",
        "wer ist erika beispiel?",
    ),
)
def test_retrieval_plan_routes_named_employee_contact_and_profile_wordings_to_personio(query):
    harness = load_harness()

    plan = harness.plan_retrieval(
        query,
        query,
        [],
        "kahle-vinci",
        {"user_id": "user-1"},
    )

    assert plan.required_tools == ("personio_directory",)


def test_person_contact_followup_with_a_prior_explicit_person_question_stays_personio_only():
    harness = load_harness()
    query = "Wie kann ich ihn erreichen?\nWer ist Erika Beispiel?"

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
        "Wie sind die Kontaktdaten von Erika Beispiel?",
        "Nenne mir die Kontaktdaten von Erika Beispiel.",
        "Zeige mir die E-Mail-Adresse von Erika Beispiel.",
        "Welche Telefonnummer hat Erika Beispiel?",
        "Wie kann ich Erika Beispiel erreichen?",
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


@pytest.mark.parametrize(
    "query",
    (
        "Wie erreiche ich das Personalwesen?",
        "Wie komme ich mit der Personalabteilung in Kontakt?",
        "Gib mir den Kontakt zum Personalbereich.",
        "Wie erreiche ich Personal?",
        "Wie erreiche ich HR?",
        "Wie erreiche ich die Buchhaltung?",
        "Wie erreiche ich die Disposition?",
        "Wie erreiche ich das Marketing?",
        "Wie erreiche ich die IT?",
        "Wie erreiche ich den Verkauf?",
        "Wie erreiche ich den Service?",
        "Wie erreiche ich den Teiledienst?",
    ),
)
def test_organization_area_contact_wordings_route_to_personio_and_rag(query):
    harness = load_harness()

    plan = harness.plan_retrieval(
        query,
        query,
        [],
        "kahle-vinci",
        {"user_id": "user-1"},
    )

    assert plan.required_tools == ("personio_directory", "rag_chat")
    assert plan.information_needs[0].kind == "organization_contact"


def test_central_organization_contact_combines_personio_and_rag_evidence():
    harness = load_harness()
    query = "Wie lautet die zentrale E-Mail-Adresse der Personalabteilung?"

    plan = harness.plan_retrieval(
        query,
        query,
        [],
        "kahle-vinci",
        {"user_id": "user-1"},
    )

    assert plan.required_tools == ("personio_directory", "rag_chat")
    assert plan.information_needs[0].kind == "organization_contact"


@pytest.mark.parametrize(
    ("query", "expected_tools"),
    (
        ("Wie erreiche ich die IT?", ("personio_directory", "rag_chat")),
        (
            "Wie ist die E-Mail der Personalabteilung?",
            ("personio_directory", "rag_chat"),
        ),
        (
            "Wer sind die Ansprechpartner im Marketing?",
            ("personio_directory", "rag_chat"),
        ),
        (
            "Welche Kontakte gibt es für Bewerbungen?",
            ("personio_directory", "rag_chat"),
        ),
        ("Wer arbeitet in der IT?", ("personio_directory",)),
        (
            "Wer ist die Führungskraft von Erika Beispiel?",
            ("personio_directory",),
        ),
        ("Wie läuft der Bewerbungsprozess?", ("rag_chat",)),
        (
            "Wohin schicke ich meine Bewerbung?",
            ("personio_directory", "rag_chat"),
        ),
    ),
)
def test_area_contact_source_matrix(query, expected_tools):
    harness = load_harness()

    plan = harness.plan_retrieval(
        query,
        query,
        [],
        "kahle-vinci",
        {"user_id": "user-1"},
    )

    assert plan.required_tools == expected_tools


@pytest.mark.parametrize(
    "query",
    (
        "Wohin schicke ich meine Bewerbung?",
        "An wen sende ich meine Bewerbung?",
        "Wo soll ich meine Krankmeldung hinschicken?",
    ),
)
def test_functional_contact_delivery_wordings_combine_personio_and_rag(query):
    harness = load_harness()

    plan = harness.plan_retrieval(
        query,
        query,
        [],
        "kahle-vinci",
        {"user_id": "user-1"},
    )

    assert plan.required_tools == ("personio_directory", "rag_chat")
    assert plan.information_needs[0].kind == "organization_contact"


@pytest.mark.parametrize(
    "query",
    (
        "Wie erreiche ich Personal?",
        "Wie erreiche ich das Personalwesen?",
        "Wie erreiche ich die Personalabteilung?",
        "Wie erreiche ich den Personalbereich?",
        "Wie erreiche ich HR?",
        "Wie erreiche ich die EDV?",
        "Wie erreiche ich das Marketing?",
        "Welche Kontakte gibt es für Datenschutz?",
        "Welche Kontakte gibt es für Krankmeldungen?",
        "Welche Kontakte gibt es für Karriere?",
    ),
)
def test_organizational_channel_wordings_combine_personio_and_rag(query):
    harness = load_harness()

    plan = harness.plan_retrieval(
        query,
        query,
        [],
        "kahle-vinci",
        {"user_id": "user-1"},
    )

    assert plan.required_tools == ("personio_directory", "rag_chat")


def test_personio_organization_contact_uses_only_structured_business_contacts():
    harness = load_harness()
    query = "Wie erreiche ich das Personalwesen?"
    personio = {
        "status": "ok",
        "claims": [{
            "display_name": "Erika Beispiel",
            "business_email": "person@example.invalid",
            "business_phone": "+49 511 000000",
            "source_id": "P1",
        }],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-31T10:15:00Z",
        "stale": False,
    }

    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result="",
        personio_result=personio,
    )

    assert decision.answer_contract.allowed_contact_values == (
        "person@example.invalid",
        "+49 511 000000",
    )
    assert decision.direct_answer() == (
        "Aktuelle Ansprechpersonen aus Personio:\n\n"
        "- Erika Beispiel – person@example.invalid · +49 511 000000"
    )


def test_mixed_organization_contact_keeps_documented_channel_and_current_people_separate():
    harness = load_harness()
    query = "Wie erreiche ich das Marketing?"
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "{\"claim_id\":\"R1C1\",\"source_id\":\"#1\","
        "\"text\":\"Das dokumentierte Funktionspostfach ist team@example.invalid.\","
        "\"evidence_span\":\"Das dokumentierte Funktionspostfach ist team@example.invalid.\"}],"
        "\"missing_information\":[],\"conflicts\":[],"
        "\"sources\":[{\"number\":1,\"document_id\":\"doc-1\"}]}"
    )
    personio = {
        "status": "ok",
        "claims": [{
            "display_name": "Erika Beispiel",
            "business_email": "person@example.invalid",
            "source_id": "P1",
        }],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-31T10:15:00Z",
        "stale": False,
    }

    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result=rag,
        personio_result=personio,
    )

    assert decision.direct_answer() == (
        "Dokumentierter Kontaktweg:\n\n"
        "Das dokumentierte Funktionspostfach ist team@example.invalid. [#1]\n\n"
        "Aktuelle Ansprechpersonen aus Personio:\n\n"
        "- Erika Beispiel – person@example.invalid"
    )


def test_general_area_contact_accepts_a_cited_non_literal_contact_path():
    harness = load_harness()
    query = "Wie erreiche ich die IT?"
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "{\"claim_id\":\"R1C1\",\"source_id\":\"#1\","
        "\"text\":\"Die IT ist ausschließlich über das Ticketsystem im Intranet erreichbar.\","
        "\"evidence_span\":\"Die IT ist ausschließlich über das Ticketsystem im Intranet erreichbar.\"}],"
        "\"missing_information\":[],\"conflicts\":[],"
        "\"sources\":[{\"number\":1,\"document_id\":\"doc-1\"}]}"
    )

    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result=rag,
    )

    assert decision.evidence_bundle.status == "partially_supported"
    assert decision.answer_contract.allowed_contact_values == ()
    assert decision.direct_answer() == (
        "Dokumentierter Kontaktweg:\n\n"
        "Die IT ist ausschließlich über das Ticketsystem im Intranet erreichbar. [#1]"
    )


def test_personio_organization_contact_requires_the_requested_contact_channel():
    harness = load_harness()
    query = "Wie lautet die E-Mail-Adresse der Personalabteilung?"
    personio = {
        "status": "ok",
        "claims": [{
            "display_name": "Erika Beispiel",
            "business_phone": "+49 511 000000",
            "source_id": "P1",
        }],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-31T10:15:00Z",
        "stale": False,
    }

    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result="",
        personio_result=personio,
    )

    assert decision.evidence_bundle.status == "unsupported"
    assert decision.answer_contract.allowed_contact_values == ()
    assert decision.direct_answer() == (
        "Dazu habe ich keine verlässliche freigegebene Kontaktinformation."
    )


def test_rag_organization_contact_without_literal_contact_evidence_is_unsupported():
    harness = load_harness()
    query = "Wie lautet die zentrale E-Mail-Adresse der Personalabteilung?"
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "{\"claim_id\":\"R1C1\",\"source_id\":\"#1\","
        "\"text\":\"Die Personalabteilung bearbeitet interne Anfragen.\","
        "\"evidence_span\":\"Die Personalabteilung bearbeitet interne Anfragen.\"}],"
        "\"missing_information\":[],\"conflicts\":[],"
        "\"sources\":[{\"number\":1,\"document_id\":\"doc-1\"}]}"
    )

    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result=rag,
    )

    assert decision.evidence_bundle.status == "unsupported"
    assert decision.direct_answer() == (
        "Dazu habe ich keine verlässliche freigegebene Kontaktinformation."
    )


def test_rag_contact_evidence_never_treats_a_document_date_as_a_phone_number():
    harness = load_harness()
    query = "Wie lautet die zentrale Telefonnummer der Personalabteilung?"
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "{\"claim_id\":\"R1C1\",\"source_id\":\"#1\","
        "\"text\":\"Der dokumentierte Stand ist 31.08.2026.\","
        "\"evidence_span\":\"Der dokumentierte Stand ist 31.08.2026.\"}],"
        "\"missing_information\":[],\"conflicts\":[],"
        "\"sources\":[{\"number\":1,\"document_id\":\"doc-1\"}]}"
    )

    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result=rag,
    )

    assert decision.evidence_bundle.status == "unsupported"
    assert decision.answer_contract.allowed_contact_values == ()


def test_rag_organization_contact_uses_only_an_exact_cited_contact_literal():
    harness = load_harness()
    query = "Wie lautet die zentrale E-Mail-Adresse der Personalabteilung?"
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "{\"claim_id\":\"R1C1\",\"source_id\":\"#1\","
        "\"text\":\"Der freigegebene Kontakt ist team@example.invalid.\","
        "\"evidence_span\":\"Der freigegebene Kontakt ist team@example.invalid.\"}],"
        "\"missing_information\":[],\"conflicts\":[],"
        "\"sources\":[{\"number\":1,\"document_id\":\"doc-1\"}]}"
    )

    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result=rag,
    )

    assert decision.evidence_bundle.status == "partially_supported"
    assert decision.answer_contract.allowed_contact_values == (
        "team@example.invalid",
    )
    assert decision.direct_answer() == (
        "Dokumentierter Kontaktweg:\n\n"
        "Der freigegebene Kontakt ist team@example.invalid. [#1]"
    )


def test_previous_assistant_contact_value_is_never_treated_as_evidence():
    harness = load_harness()
    query = "Woher hast du diese E-Mail-Adresse?"
    rag = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "EVIDENCE_BUNDLE_JSON: {\"schema_version\":\"kahle.evidence-bundle.v1\","
        "\"status\":\"supported\",\"supported_claims\":["
        "{\"claim_id\":\"R1C1\",\"source_id\":\"#1\","
        "\"text\":\"Die Quelle beschreibt nur den Aufgabenbereich.\","
        "\"evidence_span\":\"Die Quelle beschreibt nur den Aufgabenbereich.\"}],"
        "\"missing_information\":[],\"conflicts\":[],"
        "\"sources\":[{\"number\":1,\"document_id\":\"doc-1\"}]}"
    )

    decision = harness.build_decision(
        query=query,
        resolved_query="Wie lautet die zentrale E-Mail-Adresse der Personalabteilung?",
        messages=[
            {"role": "assistant", "content": "Nutze invented@example.invalid."},
            {"role": "user", "content": query},
        ],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1"},
        rag_result=rag,
    )

    assert decision.evidence_bundle.status == "unsupported"
    assert "invented@example.invalid" not in decision.answer_prompt()


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


def _result_driven_personio_payload(*, status="ok"):
    return {
        "status": status,
        "claims": (
            [
                {
                    "display_name": "Erika Beispiel",
                    "position": "Serviceassistenz",
                    "business_email": "person@example.invalid",
                    "source_id": "P1",
                }
            ]
            if status == "ok"
            else []
        ),
        "sources": (
            [{"id": "P1", "kind": "personio_directory"}]
            if status == "ok"
            else []
        ),
        "sync_completed_at": "2026-08-31T10:15:00Z",
        "stale": False,
    }


def _result_driven_rag_payload(
    *,
    supported=True,
    include_current_people=False,
    include_personio_owned_contact_field=False,
    include_personio_owned_assertion=False,
    include_personio_owned_contact_assertion=False,
    evidence_span=None,
):
    claims = []
    if supported:
        claim = {
            "claim_id": "R1C1",
            "source_id": "R1",
            "text": (
                "Der dokumentierte Kontaktweg ist das Ticketsystem; "
                "das Funktionspostfach ist team@example.invalid."
            ),
            "evidence_span": (
                "Der dokumentierte Kontaktweg ist das Ticketsystem; "
                "das Funktionspostfach ist team@example.invalid."
            ),
        }
        if include_current_people:
            claim.update(
                {
                    "display_name": "Veralteter Name",
                    "position": "Veraltete Rolle",
                }
            )
        if include_personio_owned_contact_field:
            claim["business_email"] = "erika@example.invalid"
        if include_personio_owned_assertion:
            claim.update(
                {
                    "text": (
                        "Erika Beispiel ist Serviceassistenz; ihre Führungskraft "
                        "ist Max Leitung."
                    ),
                    "evidence_span": (
                        "Erika Beispiel ist Serviceassistenz; ihre Führungskraft "
                        "ist Max Leitung."
                    ),
                }
            )
        if include_personio_owned_contact_assertion:
            claim.update(
                {
                    "text": "Erika Beispiel: erika@example.invalid.",
                    "evidence_span": "Erika Beispiel: erika@example.invalid.",
                }
            )
        if evidence_span is not None:
            claim["evidence_span"] = evidence_span
        claims.append(claim)
    return (
        "KAHLE_RAG_RESULT\nFOUND: "
        + ("true" if supported else "false")
        + "\nEVIDENCE_BUNDLE_JSON: "
        + __import__("json").dumps(
            {
                "schema_version": "kahle.evidence-bundle.v1",
                "status": "supported" if supported else "unsupported",
                "supported_claims": claims,
                "missing_information": (
                    [] if supported else ["Kein dokumentierter Kontaktweg gefunden."]
                ),
                "conflicts": [],
                "sources": [{"id": "R1", "title": "Kontaktwege"}] if supported else [],
            },
            ensure_ascii=False,
        )
    )


@pytest.mark.parametrize(
    ("called_tools", "expected_tools", "expected_sources"),
    (
        (("personio_directory",), ("personio_directory",), {"P1"}),
        (("rag_chat",), ("rag_chat",), {"R1"}),
        (
            ("personio_directory", "rag_chat"),
            ("personio_directory", "rag_chat"),
            {"P1", "R1"},
        ),
    ),
)
def test_result_driven_decision_uses_only_actually_called_sources(
    called_tools, expected_tools, expected_sources
):
    harness = load_harness()

    decision = harness.build_result_driven_decision(
        called_tools=called_tools,
        query="Kompakte freie Formulierung ohne Harness-Routing",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result=_result_driven_rag_payload(),
        personio_result=_result_driven_personio_payload(),
    )

    assert decision is not None
    assert decision.retrieval_plan.required_tools == expected_tools
    assert {source["id"] for source in decision.evidence_bundle.sources} == expected_sources


def test_result_driven_decision_is_absent_without_an_actual_internal_tool_call():
    harness = load_harness()

    decision = harness.build_result_driven_decision(
        called_tools=(),
        query="Allgemeine Unterhaltung",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result=_result_driven_rag_payload(),
        personio_result=_result_driven_personio_payload(),
    )

    assert decision is None


def test_personio_not_found_does_not_consume_unexecuted_rag_as_fallback():
    harness = load_harness()

    decision = harness.build_result_driven_decision(
        called_tools=("personio_directory",),
        query="Serviceassistenzen Neustadt",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result=_result_driven_rag_payload(),
        personio_result=_result_driven_personio_payload(status="not_found"),
    )

    assert decision is not None
    assert decision.retrieval_plan.required_tools == ("personio_directory",)
    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.sources == ()


def test_rag_unsupported_does_not_consume_unexecuted_personio_as_fallback():
    harness = load_harness()

    decision = harness.build_result_driven_decision(
        called_tools=("rag_chat",),
        query="Wie lautet das Funktionspostfach?",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result=_result_driven_rag_payload(supported=False),
        personio_result=_result_driven_personio_payload(),
    )

    assert decision is not None
    assert decision.retrieval_plan.required_tools == ("rag_chat",)
    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.sources == ()


def test_result_driven_rag_rejects_person_master_and_supervisor_assertions():
    harness = load_harness()

    decision = harness.build_result_driven_decision(
        called_tools=("rag_chat",),
        query="Freie Formulierung ohne Quellenrouting",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result=_result_driven_rag_payload(
            include_personio_owned_assertion=True
        ),
    )

    assert decision is not None
    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.supported_claims == ()
    assert decision.answer_contract.allowed_contact_values == ()


def test_result_driven_rag_rejects_named_person_contact_assertions():
    harness = load_harness()

    decision = harness.build_result_driven_decision(
        called_tools=("rag_chat",),
        query="Freie Formulierung ohne Quellenrouting",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result=_result_driven_rag_payload(
            include_personio_owned_contact_assertion=True
        ),
    )

    assert decision is not None
    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.supported_claims == ()
    assert decision.answer_contract.allowed_contact_values == ()


def test_result_driven_rag_rejects_named_person_contact_in_evidence_span():
    harness = load_harness()

    decision = harness.build_result_driven_decision(
        called_tools=("rag_chat",),
        query="Freie Formulierung ohne Quellenrouting",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result=_result_driven_rag_payload(
            evidence_span="Erika Beispiel hat die Telefonnummer +49 1234 567890."
        ),
    )

    assert decision is not None
    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.supported_claims == ()
    assert decision.answer_contract.allowed_contact_values == ()


def test_result_driven_personio_not_found_drops_rag_person_assertions():
    harness = load_harness()

    decision = harness.build_result_driven_decision(
        called_tools=("personio_directory", "rag_chat"),
        query="Freie Formulierung ohne Quellenrouting",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        personio_result=_result_driven_personio_payload(status="not_found"),
        rag_result=_result_driven_rag_payload(
            include_personio_owned_assertion=True
        ),
    )

    assert decision is not None
    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.supported_claims == ()


def test_result_driven_personio_not_found_keeps_rag_contact_path_as_partial():
    harness = load_harness()

    decision = harness.build_result_driven_decision(
        called_tools=("personio_directory", "rag_chat"),
        query="Freie Formulierung ohne Quellenrouting",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        personio_result=_result_driven_personio_payload(status="not_found"),
        rag_result=_result_driven_rag_payload(),
    )

    assert decision is not None
    assert decision.evidence_bundle.status == "partially_supported"
    assert any(
        isinstance(claim, dict) and "Ticketsystem" in str(claim.get("text") or "")
        for claim in decision.evidence_bundle.supported_claims
    )


@pytest.mark.parametrize(
    ("called_tools", "personio_result"),
    (
        (("rag_chat",), None),
        (("personio_directory", "rag_chat"), _result_driven_personio_payload(status="not_found")),
    ),
)
def test_result_driven_rag_sanitizes_structured_personio_fields_without_dropping_documented_path(
    called_tools, personio_result
):
    harness = load_harness()

    decision = harness.build_result_driven_decision(
        called_tools=called_tools,
        query="Freie Formulierung ohne Quellenrouting",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        personio_result=personio_result,
        rag_result=_result_driven_rag_payload(
            include_current_people=True,
            include_personio_owned_contact_field=True,
        ),
    )

    assert decision is not None
    assert decision.evidence_bundle.status == "partially_supported"
    claim = decision.evidence_bundle.supported_claims[0]
    assert claim["text"].startswith("Der dokumentierte Kontaktweg")
    assert all(
        field not in claim
        for field in ("display_name", "position", "business_email")
    )
    assert decision.answer_contract.allowed_contact_values == ("team@example.invalid",)


@pytest.mark.parametrize(
    ("claim_text", "called_tools", "personio_result"),
    (
        (
            "Erika Beispiel hat Max Leitung als Führungskraft.",
            ("rag_chat",),
            None,
        ),
        (
            "Max Leitung ist Vorgesetzter von Erika Beispiel.",
            ("personio_directory", "rag_chat"),
            _result_driven_personio_payload(status="not_found"),
        ),
        (
            "Erika Beispiel hat die Telefonnummer +49 1234 567890.",
            ("rag_chat",),
            None,
        ),
    ),
)
def test_result_driven_rag_rejects_named_person_relationship_and_contact_formulations(
    claim_text, called_tools, personio_result
):
    harness = load_harness()
    rag_result = _result_driven_rag_payload().replace(
        "Der dokumentierte Kontaktweg ist das Ticketsystem; "
        "das Funktionspostfach ist team@example.invalid.",
        claim_text,
    )

    decision = harness.build_result_driven_decision(
        called_tools=called_tools,
        query="Freie Formulierung ohne Quellenrouting",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        personio_result=personio_result,
        rag_result=rag_result,
    )

    assert decision is not None
    assert decision.evidence_bundle.status == "unsupported"
    assert decision.evidence_bundle.supported_claims == ()
    assert decision.answer_contract.allowed_contact_values == ()


@pytest.mark.parametrize(
    "claim_text",
    (
        "Kahle Gruppe ist über team@example.invalid erreichbar.",
        "Das Team Buchhaltung ist unter team@example.invalid erreichbar.",
    ),
)
def test_result_driven_rag_keeps_functional_contacts_without_person_subject(claim_text):
    harness = load_harness()
    rag_result = _result_driven_rag_payload().replace(
        "Der dokumentierte Kontaktweg ist das Ticketsystem; "
        "das Funktionspostfach ist team@example.invalid.",
        claim_text,
    )

    decision = harness.build_result_driven_decision(
        called_tools=("rag_chat",),
        query="Freie Formulierung ohne Quellenrouting",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result=rag_result,
    )

    assert decision is not None
    assert decision.evidence_bundle.status == "supported"
    assert decision.evidence_bundle.supported_claims[0]["text"] == claim_text
    assert decision.answer_contract.allowed_contact_values == ("team@example.invalid",)


def test_result_driven_mixed_evidence_keeps_personio_authority_and_rag_path():
    harness = load_harness()

    decision = harness.build_result_driven_decision(
        called_tools=("rag_chat", "personio_directory"),
        query="Wer arbeitet aktuell dort und wie ist der dokumentierte Kontaktweg?",
        messages=[],
        model_id="kahle-vinci",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result=_result_driven_rag_payload(include_current_people=True),
        personio_result=_result_driven_personio_payload(),
    )

    assert decision is not None
    claims = decision.evidence_bundle.supported_claims
    assert claims[0]["display_name"] == "Erika Beispiel"
    assert claims[0]["position"] == "Serviceassistenz"
    assert all(
        not isinstance(claim, dict)
        or (
            claim.get("display_name") != "Veralteter Name"
            and claim.get("position") != "Veraltete Rolle"
        )
        for claim in claims
    )
    assert any(
        isinstance(claim, dict) and "Ticketsystem" in str(claim.get("text") or "")
        for claim in claims
    )
    assert decision.answer_contract.allowed_contact_values == (
        "person@example.invalid",
        "team@example.invalid",
    )
