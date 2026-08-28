from __future__ import annotations

import pytest


class FakePersonioClient:
    def __init__(self, result: dict[str, Any], *, started=None, release=None):
        self.result = result
        self.calls = []
        self.started = started
        self.release = release

    async def search(self, query, intent, user_id, user_role, *, candidate_query=""):
        self.calls.append((query, intent, user_id, user_role, candidate_query))
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        return self.result

class FakeResponse:
    def __init__(self, *, status: int, payload: Any):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self):
        return self._payload

class FakeSession:
    def __init__(self, response: FakeResponse, captured: dict[str, Any]):
        self.response = response
        self.captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def post(self, url, **kwargs):
        self.captured.update(url=url, **kwargs)
        return self.response

def load_python_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def load_planned_retrieval_executor():
    return load_function_from_middleware("_execute_kahle_retrieval_plan")

def load_retrieval_gate():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_plan_kahle_retrieval_gate"
    )
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    harness = load_python_module(HARNESS, "kahle_harness_gate")
    namespace = {
        "Any": Any,
        "plan_knowledge_retrieval": harness.plan_retrieval,
        "replace": replace,
    }
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_plan_kahle_retrieval_gate"]

def retrieval_plan(query: str, *, role: str = "user"):
    harness = load_python_module(HARNESS, f"kahle_harness_{abs(hash((query, role)))}")
    return harness.plan_retrieval(
        query=query,
        resolved_query=query,
        messages=[{"role": "user", "content": query}],
        model_id="test-model",
        permission_scope={"user_id": "user-1", "role": role, "groups": []},
    )

def test_pure_person_query_calls_personio_once_and_never_falls_back_to_rag():
    execute = load_planned_retrieval_executor()
    query = "Wo arbeitet Max Mustermann?"
    personio = FakePersonioClient(
        {
            "status": "not_found",
            "claims": [],
            "sources": [],
            "sync_completed_at": "2026-08-24T10:15:00Z",
            "stale": False,
        }
    )
    rag_calls = []

    async def rag_retriever():
        rag_calls.append(query)
        return "must-not-run"

    metadata = {}
    result = asyncio.run(
        execute(
            retrieval_plan(query),
            query=query,
            directory_intent="person_lookup",
            user_id="user-1",
            user_role="user",
            personio_client=personio,
            rag_retriever=rag_retriever,
            metadata=metadata,
        )
    )

    assert personio.calls == [(query, "person_lookup", "user-1", "user", "")]
    assert rag_calls == []
    assert result["personio_result"]["status"] == "not_found"
    assert result["rag_result"] == ""
    assert metadata["kahle_retrieval_tools"] == ["personio_directory"]

    harness = load_python_module(HARNESS, "kahle_harness_personio_not_found")
    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[{"role": "user", "content": query}],
        model_id="test-model",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result=result["rag_result"],
        personio_result=result["personio_result"],
    )
    direct_answer = load_function_from_middleware(
        "_knowledge_harness_direct_answer"
    )
    assert direct_answer(decision, decision.to_dict()) == (
        "Dazu finde ich im aktuellen Personio-Mitarbeiterverzeichnis keine "
        "passende freigegebene Information."
    )


def test_supported_onboarding_directory_evidence_is_rendered_without_model_synthesis():
    query = "Wie viele Mitarbeiter sind aktuell im Onboarding?"
    personio = {
        "status": "ok",
        "claims": [
            {
                "display_name": "Nora Neu",
                "position": "Serviceberaterin",
                "department": "Service",
                "team": "Service Hannover",
                "office": "Hannover",
                "business_email": "nora.neu@kahle.de",
                "personio_id": "17",
                "source_id": "P1",
            },
            {
                "display_name": "Erik Einstieg",
                "position": "Verkäufer",
                "department": "Verkauf",
                "team": "SEAT",
                "office": "Wedemark",
                "source_id": "P2",
            },
        ],
        "sources": [
            {"id": "P1", "kind": "personio_directory"},
            {"id": "P2", "kind": "personio_directory"},
        ],
        "sync_completed_at": "2026-08-26T15:44:00Z",
        "stale": False,
    }
    harness = load_python_module(HARNESS, "kahle_harness_onboarding_direct_answer")
    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[{"role": "user", "content": query}],
        model_id="test-model",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result="",
        personio_result=personio,
    )

    direct_answer = load_function_from_middleware("_knowledge_harness_direct_answer")
    answer = direct_answer(decision, decision.to_dict())

    assert answer.startswith("Aktuell sind 2 Mitarbeiter im Onboarding:")
    assert "Nora Neu – Serviceberaterin" in answer
    assert "Erik Einstieg – Verkäufer" in answer
    assert "nora.neu@kahle.de" not in answer
    assert "personio_id" not in answer


def test_supported_person_lookup_evidence_uses_the_answer_contract_instead_of_a_fixed_renderer():
    query = "Was weißt du alles über Erika Beispiel?"
    personio = {
        "status": "ok",
        "claims": [
            {
                "display_name": "Erika Marie Beispiel",
                "position": "Serviceberaterin",
                "department": "Service",
                "team": "Service Hannover",
                "office": "Hannover",
                "business_email": "erika.beispiel@kahle.de",
                "business_phone": "+49 511 123456",
                "personio_id": "17",
                "source_id": "P1",
            }
        ],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-26T15:44:00Z",
        "stale": False,
    }
    harness = load_python_module(HARNESS, "kahle_harness_person_lookup_direct_answer")
    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[{"role": "user", "content": query}],
        model_id="test-model",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result="",
        personio_result=personio,
    )

    direct_answer = load_function_from_middleware("_knowledge_harness_direct_answer")
    answer = direct_answer(decision, decision.to_dict())

    assert answer == ""
    contract = decision.answer_prompt()
    assert "Erika Marie Beispiel" in contract
    assert "erika.beispiel@kahle.de" in contract
    assert "+49 511" in contract


def test_supported_person_contact_evidence_uses_the_answer_contract_instead_of_a_fixed_renderer():
    query = "Wie erreiche ich Erika Beispiel?"
    personio = {
        "status": "ok",
        "claims": [
            {
                "display_name": "Erika Beispiel",
                "position": "Serviceberaterin",
                "business_email": "erika.beispiel@kahle.de",
                "business_phone": "+49 511 123456",
                "personio_id": "17",
                "source_id": "P1",
            }
        ],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-26T15:44:00Z",
        "stale": False,
    }
    harness = load_python_module(HARNESS, "kahle_harness_person_contact_direct_answer")
    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[{"role": "user", "content": query}],
        model_id="test-model",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result="",
        personio_result=personio,
    )

    direct_answer = load_function_from_middleware("_knowledge_harness_direct_answer")
    answer = direct_answer(decision, decision.to_dict())

    assert answer == ""
    contract = decision.answer_prompt()
    assert "erika.beispiel@kahle.de" in contract
    assert "+49 511 123456" in contract


def test_general_leadership_ranking_is_fail_closed_even_with_directory_evidence():
    query = "Wer sind die wichtigsten Führungskräfte?"
    personio = {
        "status": "ok",
        "claims": [
            {"display_name": "Erika Beispiel", "position": "Leitung", "source_id": "P1"}
        ],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-26T15:44:00Z",
        "stale": False,
    }
    harness = load_python_module(HARNESS, "kahle_harness_leadership_direct_answer")
    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[{"role": "user", "content": query}],
        model_id="test-model",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result="",
        personio_result=personio,
    )

    direct_answer = load_function_from_middleware("_knowledge_harness_direct_answer")
    answer = direct_answer(decision, decision.to_dict())

    assert answer == (
        "Eine Rangliste oder Auswahl wichtiger Führungskräfte kann ich nicht "
        "verlässlich bestimmen. Personio liefert dafür keine freigegebene Evidenz."
    )
    assert "Erika Beispiel" not in answer


def test_named_supervisor_evidence_is_not_blocked_as_a_leadership_ranking():
    query = "Wer ist die Führungskraft von Erika Beispiel?"
    personio = {
        "status": "ok",
        "claims": [
            {"display_name": "Max Leitung", "position": "Bereichsleitung", "source_id": "P1"}
        ],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-26T15:44:00Z",
        "stale": False,
    }
    harness = load_python_module(HARNESS, "kahle_harness_named_supervisor_direct_answer")
    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[{"role": "user", "content": query}],
        model_id="test-model",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result="",
        personio_result=personio,
    )

    direct_answer = load_function_from_middleware("_knowledge_harness_direct_answer")

    assert direct_answer(decision, decision.to_dict()) == ""
    assert "Max Leitung" in decision.answer_prompt()


def test_supervisor_follow_up_passes_the_previous_directory_question_as_private_context():
    execute = load_planned_retrieval_executor()
    query = "Wer davon ist die Führungskraft?"
    prior_query = "Wer arbeitet im Teiledienst in Hannover?"
    personio = FakePersonioClient(
        {
            "status": "not_found",
            "claims": [],
            "sources": [],
            "sync_completed_at": "2026-08-24T10:15:00Z",
            "stale": False,
        }
    )

    result = asyncio.run(
        execute(
            retrieval_plan(query),
            query=query,
            directory_intent="supervisor_lookup",
            supervisor_candidate_query=prior_query,
            user_id="user-1",
            user_role="user",
            personio_client=personio,
            rag_retriever=lambda: None,
            metadata={},
        )
    )

    assert result["rag_result"] == ""
    assert personio.calls == [
        (query, "supervisor_lookup", "user-1", "user", prior_query)
    ]


def test_german_was_weisst_du_ueber_question_uses_person_lookup_intent():
    personio_intent = load_personio_directory_intent()

    assert personio_intent("Was weißt du über Max Mustermann?") == "person_lookup"
    assert (
        personio_intent("Was weißt du alles über Max Mustermann?") == "person_lookup"
    )


def test_german_fuehrungskraft_question_uses_supervisor_lookup_intent():
    personio_intent = load_personio_directory_intent()

    assert (
        personio_intent("Wer ist die Führungskraft von Erika Beispiel?")
        == "supervisor_lookup"
    )


def test_supervisor_typo_uses_supervisor_lookup_intent():
    personio_intent = load_personio_directory_intent()

    assert (
        personio_intent("Wer ist die Führungskrft von Erika Beispiel?")
        == "supervisor_lookup"
    )


def test_supervisor_typo_blocks_rag_person_claim_as_defense_in_depth():
    class UnsafeRagDecision:
        @staticmethod
        def direct_answer():
            return (
                "Erika Beispiel berichtet an eine erfundene Führungskraft. "
                "Quelle: Personio-Mitarbeiterverzeichnis."
            )

    payload = {
        "retrieval_plan": {"required_tools": ["rag_chat"]},
        "evidence_bundle": {
            "status": "supported",
            "supported_claims": ["Erfundene aktuelle Supervisor-Aussage"],
        },
        "resolved_context": {
            "retrieval_query": "Wer ist die Führungskrft von Erika Beispiel?"
        },
    }

    direct_answer = load_function_from_middleware("_knowledge_harness_direct_answer")
    answer = direct_answer(UnsafeRagDecision(), payload)

    assert answer == (
        "Dazu finde ich im aktuellen Personio-Mitarbeiterverzeichnis keine "
        "passende freigegebene Supervisor-Evidenz."
    )
    assert "erfundene Führungskraft" not in answer
    assert "Quelle: Personio" not in answer


@pytest.mark.parametrize(
    ("query", "expected"),
    (
        ("Wie erreiche ich Erika Beispiel?", "person_lookup"),
        ("Wie ist die Telefonnummer von Erika Beispiel?", "person_lookup"),
        ("Wie sind die Kontaktdaten von Erika Beispiel?", "person_lookup"),
        ("Wie lauten die Kontaktdaten von Erika Beispiel?", "person_lookup"),
        ("Nenne mir die Kontaktdaten von Erika Beispiel.", "person_lookup"),
        ("Gib mir die Kontaktdaten von Erika Beispiel.", "person_lookup"),
        ("Gib mir bitte die Kontaktdaten von Erika Beispiel.", "person_lookup"),
        ("Bitte gib mir den Kontakt von Erika Beispiel.", "person_lookup"),
        ("Kannst du mir die E-Mail-Adresse von Erika Beispiel geben?", "person_lookup"),
        ("Ich brauche die Telefonnummer von Erika Beispiel.", "person_lookup"),
        ("Gib mir Infos ueber Erika Beispiel.", "person_lookup"),
        ("wer ist erika beispiel?", "person_lookup"),
        ("Zeige mir die E-Mail-Adresse von Erika Beispiel.", "person_lookup"),
        ("Welche Telefonnummer hat Erika Beispiel?", "person_lookup"),
        ("Wie kann ich Erika Beispiel erreichen?", "person_lookup"),
        ("Wie sind die Kontaktdaten der Serviceleitung Nienburg?", "directory_search"),
    ),
)
def test_current_employee_contact_questions_use_directory_intents(query, expected):
    personio_intent = load_personio_directory_intent()

    assert personio_intent(query) == expected


def test_german_wie_haengen_question_uses_person_lookup_intent():
    personio_intent = load_personio_directory_intent()

    assert (
        personio_intent("Wie hängen Max Mustermann und KAHLE-Vinci zusammen?")
        == "person_lookup"
    )

def test_actual_middleware_gate_plans_directory_and_mixed_queries_before_legacy_rag_gate():
    gate = load_retrieval_gate()
    legacy_gate = load_rag_routing_helpers()
    cases = {
        "Wo arbeitet Max Mustermann?": ("personio_directory",),
        "Was hat Stefan Schrader mit VSX zu tun?": (
            "personio_directory",
            "rag_chat",
        ),
    }

    for query, expected_tools in cases.items():
        assert legacy_gate(query) is False
        plan = gate(
            query=query,
            resolved_query=query,
            messages=[{"role": "user", "content": query}],
            model_id="test-model",
            permission_scope={"user_id": "user-1", "role": "user"},
            tools_dict={"rag_chat": object()},
            legacy_rag_request=False,
            harness_mode="active",
        )
        assert plan is not None
        assert plan.required_tools == expected_tools

def test_actual_middleware_gate_respects_explicit_harness_off_for_directory_calls():
    gate = load_retrieval_gate()
    query = "Wo arbeitet Max Mustermann?"

    assert gate(
        query=query,
        resolved_query=query,
        messages=[{"role": "user", "content": query}],
        model_id="test-model",
        permission_scope={"user_id": "user-1", "role": "user"},
        tools_dict={"rag_chat": object()},
        legacy_rag_request=False,
        harness_mode="off",
    ) is None

    legacy_plan = gate(
        query="Was ist bei uns zu VSX dokumentiert?",
        resolved_query="Was ist bei uns zu VSX dokumentiert?",
        messages=[
            {"role": "user", "content": "Was ist bei uns zu VSX dokumentiert?"}
        ],
        model_id="test-model",
        permission_scope={"user_id": "user-1", "role": "user"},
        tools_dict={"rag_chat": object()},
        legacy_rag_request=True,
        harness_mode="off",
    )
    assert legacy_plan is not None
    assert legacy_plan.required_tools == ("rag_chat",)

def test_pending_user_calls_neither_personio_nor_rag():
    execute = load_planned_retrieval_executor()
    query = "Wo arbeitet Max Mustermann?"
    personio = FakePersonioClient({"status": "ok", "claims": [], "sources": []})
    rag_calls = []

    async def rag_retriever():
        rag_calls.append(query)
        return "must-not-run"

    metadata = {}
    result = asyncio.run(
        execute(
            retrieval_plan(query, role="pending"),
            query=query,
            directory_intent="person_lookup",
            user_id="pending-1",
            user_role="pending",
            personio_client=personio,
            rag_retriever=rag_retriever,
            metadata=metadata,
        )
    )

    assert personio.calls == []
    assert rag_calls == []
    assert result == {"rag_result": "", "personio_result": None}
    assert metadata["kahle_retrieval_tools"] == []
    assert metadata["kahle_retrieval_access_denied"] is True

def test_mixed_person_and_project_query_starts_both_retrievers_before_release():
    execute = load_planned_retrieval_executor()
    harness = load_python_module(HARNESS, "kahle_harness_mixed_retrieval")
    query = "Was hat Stefan Schrader mit VSX zu tun?"
    personio_started = asyncio.Event()
    rag_started = asyncio.Event()
    release = asyncio.Event()
    personio = FakePersonioClient(
        {
            "status": "ok",
            "claims": [{"display_name": "Stefan Schrader", "source_id": "P1"}],
            "sources": [{"id": "P1", "kind": "personio_directory"}],
            "sync_completed_at": "2026-08-24T10:15:00Z",
            "stale": False,
        },
        started=personio_started,
        release=release,
    )

    async def rag_retriever():
        rag_started.set()
        await release.wait()
        return (
            "KAHLE_RAG_RESULT\nFOUND: true\n"
            "KONTEXT (zitierbar mit [#]):\n"
            "[#1 | interne-doku | VSX.md | chunk 1 | score 0.91]\n"
            "Stefan Schrader begleitet das Projekt VSX.\n"
            "SOURCES_JSON: "
            + json.dumps([{"id": "R1", "title": "VSX", "source_url": "/wissen/api/portal/sources/vsx"}])
        )

    async def scenario():
        metadata = {}
        task = asyncio.create_task(
            execute(
                retrieval_plan(query),
                query=query,
                directory_intent="person_lookup",
                user_id="user-1",
                user_role="user",
                personio_client=personio,
                rag_retriever=rag_retriever,
                metadata=metadata,
            )
        )
        await asyncio.wait_for(
            asyncio.gather(personio_started.wait(), rag_started.wait()), timeout=0.5
        )
        assert not task.done()
        release.set()
        return await task, metadata

    result, metadata = asyncio.run(scenario())

    decision = harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[{"role": "user", "content": query}],
        model_id="test-model",
        permission_scope={"user_id": "user-1", "role": "user", "groups": []},
        rag_result=result["rag_result"],
        personio_result=result["personio_result"],
    )
    metadata_payload = load_function_from_middleware(
        "_knowledge_harness_metadata_payload"
    )
    metadata["kahle_knowledge_harness_shadow"] = metadata_payload(decision)

    request = SimpleNamespace(state=SimpleNamespace())
    store_ephemeral = load_function_from_middleware(
        "_store_ephemeral_kahle_harness_payload"
    )
    read_ephemeral = load_function_from_middleware(
        "_ephemeral_kahle_harness_payload"
    )
    store_ephemeral(request, decision.to_dict())

    assert result["personio_result"]["sources"] == [
        {"id": "P1", "kind": "personio_directory"}
    ]
    assert "VSX.md" in result["rag_result"]
    assert metadata["kahle_retrieval_tools"] == ["personio_directory", "rag_chat"]
    assert metadata["kahle_knowledge_harness_shadow"]["evidence_status"] == "supported"
    assert metadata["kahle_knowledge_harness_shadow"]["sources"] == [
        {"id": "P1", "kind": "personio_directory"},
        {"id": "R1", "kind": "rag_chat"},
    ]
    assert set(metadata["kahle_knowledge_harness_shadow"]) == {
        "required_tools",
        "evidence_status",
        "sources",
        "stale",
        "sync_completed_at",
        "validation",
    }
    technical_json = json.dumps(
        metadata["kahle_knowledge_harness_shadow"], ensure_ascii=False
    )
    for private_value in (
        query,
        "Stefan Schrader",
        "display_name",
        "supported_claims",
        "user-1",
        "VSX.md",
        "/wissen/api/portal/sources/vsx",
    ):
        assert private_value not in technical_json
    assert read_ephemeral(request)["evidence_bundle"]["supported_claims"]

def test_personio_client_posts_bound_user_context_and_validates_response():
    module = load_python_module(PERSONIO_CLIENT, "personio_directory_client_success")
    captured = {}
    payload = {
        "status": "ok",
        "claims": [{"display_name": "Max Mustermann", "source_id": "P1"}],
        "sources": [{"id": "P1", "kind": "personio_directory"}],
        "sync_completed_at": "2026-08-24T10:15:00Z",
        "stale": False,
    }
    client = module.PersonioDirectoryClient(
        base_url="http://personio-directory:8094",
        api_key="internal-key",
        session_factory=lambda **_: FakeSession(FakeResponse(status=200, payload=payload), captured),
    )

    result = asyncio.run(
        client.search("Wo arbeitet Max Mustermann?", "person_lookup", "user-1", "admin")
    )

    assert result == payload
    assert captured["url"] == "http://personio-directory:8094/internal/search"
    assert captured["headers"] == {"X-API-Key": "internal-key"}
    assert captured["json"] == {
        "query": "Wo arbeitet Max Mustermann?",
        "intent": "person_lookup",
        "user_id": "user-1",
        "user_role": "admin",
    }


def test_personio_client_passes_only_a_supervisor_candidate_query_to_the_private_api():
    module = load_python_module(PERSONIO_CLIENT, "personio_directory_client_supervisor_context")
    captured = {}
    payload = {
        "status": "not_found",
        "claims": [],
        "sources": [],
        "sync_completed_at": "2026-08-24T10:15:00Z",
        "stale": False,
    }
    client = module.PersonioDirectoryClient(
        base_url="http://personio-directory:8094",
        api_key="internal-key",
        session_factory=lambda **_: FakeSession(FakeResponse(status=200, payload=payload), captured),
    )

    result = asyncio.run(
        client.search(
            "Wer davon ist die Führungskraft?",
            "supervisor_lookup",
            "user-1",
            "admin",
            candidate_query="Wer arbeitet im Teiledienst in Hannover?",
        )
    )

    assert result == payload
    assert captured["json"] == {
        "query": "Wer davon ist die Führungskraft?",
        "intent": "supervisor_lookup",
        "user_id": "user-1",
        "user_role": "admin",
        "candidate_query": "Wer arbeitet im Teiledienst in Hannover?",
    }

def test_personio_client_returns_only_sanitized_unavailable_error_for_invalid_schema():
    module = load_python_module(PERSONIO_CLIENT, "personio_directory_client_invalid")
    captured = {}
    client = module.PersonioDirectoryClient(
        base_url="http://personio-directory:8094",
        api_key="internal-key",
        session_factory=lambda **_: FakeSession(
            FakeResponse(status=200, payload={"status": "ok", "claims": "private payload"}),
            captured,
        ),
    )

    result = asyncio.run(
        client.search("Wo arbeitet Max Mustermann?", "person_lookup", "user-1", "user")
    )

    assert result == {
        "status": "directory_unavailable",
        "claims": [],
        "sources": [],
        "sync_completed_at": None,
        "stale": False,
    }

def test_personio_client_rejects_unapproved_claim_fields_at_openwebui_boundary():
    module = load_python_module(PERSONIO_CLIENT, "personio_directory_client_private")
    captured = {}
    client = module.PersonioDirectoryClient(
        base_url="http://personio-directory:8094",
        api_key="internal-key",
        session_factory=lambda **_: FakeSession(
            FakeResponse(
                status=200,
                payload={
                    "status": "ok",
                    "claims": [
                        {
                            "display_name": "Max Mustermann",
                            "source_id": "P1",
                            "private_phone": "+49 170 000000",
                        }
                    ],
                    "sources": [{"id": "P1", "kind": "personio_directory"}],
                    "sync_completed_at": "2026-08-24T10:15:00Z",
                    "stale": False,
                },
            ),
            captured,
        ),
    )

    result = asyncio.run(
        client.search("Wer ist Max Mustermann?", "person_lookup", "user-1", "user")
    )

    assert result["status"] == "directory_unavailable"
    assert "+49 170 000000" not in json.dumps(result)

def test_personio_client_rejects_unsanitized_sync_timestamp():
    module = load_python_module(PERSONIO_CLIENT, "personio_directory_client_timestamp")
    captured = {}
    client = module.PersonioDirectoryClient(
        base_url="http://personio-directory:8094",
        api_key="internal-key",
        session_factory=lambda **_: FakeSession(
            FakeResponse(
                status=200,
                payload={
                    "status": "ok",
                    "claims": [{"display_name": "Max Mustermann", "source_id": "P1"}],
                    "sources": [{"id": "P1", "kind": "personio_directory"}],
                    "sync_completed_at": "Max Mustermann private timestamp",
                    "stale": True,
                },
            ),
            captured,
        ),
    )

    result = asyncio.run(
        client.search("Wer ist Max Mustermann?", "person_lookup", "user-1", "user")
    )

    assert result["status"] == "directory_unavailable"
    assert "Max Mustermann" not in json.dumps(result)

def test_observable_tool_called_value_tracks_single_and_mixed_retrievals():
    tool_called = load_function_from_middleware("_knowledge_harness_tool_called")

    assert tool_called({"kahle_retrieval_tools": ["personio_directory"]}) == "personio_directory"
    assert tool_called({"kahle_retrieval_tools": ["rag_chat"]}) == "rag_chat"
    assert tool_called(
        {"kahle_retrieval_tools": ["personio_directory", "rag_chat"]}
    ) == "multi_source"
    assert tool_called({"kahle_retrieval_tools": []}) == ""

def test_personio_knowledge_route_does_not_depend_on_model_tool_assignment():
    should_prepare = load_function_from_middleware("_should_prepare_knowledge_route")

    assert should_prepare({}, True) is True
    assert should_prepare({"rag_chat": object()}, False) is True
    assert should_prepare({}, False) is False

def test_planned_directory_retrieval_does_not_depend_on_native_function_calling():
    should_execute = load_function_from_middleware(
        "_should_execute_kahle_retrieval"
    )

    assert should_execute(retrieval_plan("Wo arbeitet Max Mustermann?"), {}) is True
    assert should_execute(
        retrieval_plan("Was sagt unsere interne Richtlinie?"),
        {"rag_chat": object()},
    ) is True

import asyncio
import ast
import copy
import importlib.util
import json
import re
import unicodedata
from dataclasses import replace
from typing import Any, Optional
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIDDLEWARE = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "middleware.py"
PERSONIO_CLIENT = (
    ROOT
    / "open-webui-overrides"
    / "open_webui"
    / "utils"
    / "personio_directory_client.py"
)
HARNESS = (
    ROOT
    / "open-webui-overrides"
    / "open_webui"
    / "utils"
    / "kahle_knowledge_harness.py"
)


def load_rag_routing_helpers():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {
        "_ascii_fold",
        "_contains_token",
        "_looks_like_raw_email_text",
        "_looks_like_email_drafting_request",
        "_looks_like_user_supplied_email_drafting_request",
        "_has_explicit_internal_lookup_intent",
        "_looks_like_named_person_question",
        "_looks_like_internal_rag_request",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"re": re, "unicodedata": unicodedata}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_looks_like_internal_rag_request"]


def load_mail_redirect_helper():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {
        "_ascii_fold",
        "_looks_like_email_drafting_request",
        "_has_explicit_internal_lookup_intent",
        "_looks_like_user_supplied_email_drafting_request",
        "_is_general_kahle_vinci_model",
        "_general_vinci_mail_redirect",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"Any": Any, "re": re, "unicodedata": unicodedata}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_general_vinci_mail_redirect"]


def load_mailer_initial_question_helper():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {
        "_ascii_fold",
        "_is_mailer_vinci_model",
        "_mailer_initial_questions",
        "_mailer_initial_question_response",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"Any": Any, "re": re, "unicodedata": unicodedata}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_mailer_initial_question_response"]


def load_mailer_followup_routing_helper():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {
        "_ascii_fold",
        "_has_explicit_internal_lookup_intent",
        "_is_mailer_vinci_model",
        "_mailer_followup_uses_supplied_drafting_context",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"Any": Any, "re": re, "unicodedata": unicodedata}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_mailer_followup_uses_supplied_drafting_context"]


def load_native_rag_fallback():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {
        "_ascii_fold",
        "_contains_token",
        "_looks_like_raw_email_text",
        "_looks_like_email_drafting_request",
        "_looks_like_user_supplied_email_drafting_request",
        "_has_explicit_internal_lookup_intent",
        "_looks_like_named_person_question",
        "_looks_like_internal_rag_request",
        "_build_native_rag_fallback",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Any": Any,
        "asyncio": asyncio,
        "re": re,
        "unicodedata": unicodedata,
        "uuid4": lambda: type("FixedUuid", (), {"hex": "a" * 32})(),
        "json": __import__("json"),
    }
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_build_native_rag_fallback"]


def load_function_from_middleware(name: str):
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    aliases = {
        "TD": "Teiledienst",
        "VK": "Verkauf",
        "NIE": "Nienburg",
        "HAN": "Hannover",
        "SHG": "Stadthagen",
    }
    namespace = {
        "Any": Any,
        "asyncio": asyncio,
        "json": __import__("json"),
        "output_id": lambda prefix: f"{prefix}-fixed",
        "re": re,
        "unicodedata": unicodedata,
        "resolve_query_aliases": lambda query: __import__("functools").reduce(
            lambda value, item: re.sub(
                rf"(?<!\w){re.escape(item[0])}(?!\w)",
                item[1],
                value,
                flags=re.IGNORECASE,
            ),
            aliases.items(),
            str(query or ""),
        ),
    }
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    harness = load_python_module(HARNESS, f"kahle_harness_{name}_dependency")
    namespace["_personio_directory_intent"] = (
        harness.classify_personio_directory_intent
    )
    return namespace[name]


def load_personio_directory_intent():
    intent = load_function_from_middleware("_personio_directory_intent")
    harness = load_python_module(HARNESS, "kahle_harness_directory_intent")
    intent.__globals__["classify_personio_directory_intent"] = (
        harness.classify_personio_directory_intent
    )
    return intent


def load_canonical_rag_source_helpers():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {
        "_extract_kahle_rag_sources",
        "_canonical_kahle_rag_source_events",
        "_append_canonical_rag_source_links",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"Any": Any, "re": re, "json": __import__("json")}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace


def load_canonical_rag_feedback_helpers():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {"_extract_kahle_rag_feedback_link", "_append_canonical_rag_feedback_link"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"Any": Any, "re": re}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace


def test_stream_strip_hides_json_toolcall():
    strip = load_function_from_middleware("_strip_pseudo_toolcall_stream_text")
    assert strip('{\n  "tool": "safe_webcaller",\n  "parameters": {"query": "x"}\n}') == ""
    assert strip('{"tool_calls": [{"name": "safe_websearch"}]}') == ""
    assert strip('  {"name": "rag_chat", "parameters": {}}') == ""


def test_stream_strip_keeps_normal_answer_and_legacy_marker():
    strip = load_function_from_middleware("_strip_pseudo_toolcall_stream_text")
    assert strip("Zusammenfassung: Die Foerderung betraegt 6000 Euro.") == "Zusammenfassung: Die Foerderung betraegt 6000 Euro."
    assert strip("Hier ist die Antwort.[TOOL_CALLS]safe_websearch{}") == "Hier ist die Antwort."
    # A normal JSON snippet that is not a tool call must be preserved.
    assert strip('{"foerderung": 6000}') == '{"foerderung": 6000}'


def test_stream_strip_hides_partial_json_toolcall_while_streaming():
    """The thinking model (Responses API) pretty-prints a JSON tool call as the
    visible answer; it streams in incrementally. Every partial prefix the stream
    emits must already be blanked, otherwise the raw '{ "tool" ...' fragment
    flashes in the UI before the outlet guard replaces it."""
    strip = load_function_from_middleware("_strip_pseudo_toolcall_stream_text")
    # Real captured shape from kahle-vinci-thinking (leading newline, multi-line).
    full = '\n{\n  "tool": "safe_webcaller",\n  "parameters": {"query": "Elektroauto 2026"}\n}'
    for i in range(1, len(full) + 1):
        out = strip(full[:i])
        assert "{" not in out and "tool" not in out and "safe_webcaller" not in out, (
            f"leaked raw tool-call fragment at prefix length {i}: {out!r}"
        )
    assert strip(full) == ""


def test_stream_strip_reveals_legit_json_once_first_key_known():
    """A legit JSON answer whose first key is not a tool-call key must survive,
    even though its opening brace is briefly held back while streaming."""
    strip = load_function_from_middleware("_strip_pseudo_toolcall_stream_text")
    assert strip('{"foerderung": 6000, "jahr": 2026}') == '{"foerderung": 6000, "jahr": 2026}'
    # While the first key is still incomplete, the partial brace is held back
    # (returns empty) so nothing flashes; this is acceptable for a JSON answer.
    assert strip('{"foer') == ""
    assert strip('{"foer"') == ""
    # Content that merely starts with '{' but is not a string-keyed object
    # (e.g. a template) must not be over-suppressed.
    assert strip('{{kunde.name}}, willkommen!') == '{{kunde.name}}, willkommen!'
    assert strip('{}') == '{}'


def test_internal_rag_routing_detects_recovery_gutschein():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("Ich habe einen Kunden mit Recovery Gutschein, was muss ich machen?") is True


def test_internal_rag_routing_detects_wps_appointment_process():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("Wie plane ich einen Termin im WPS?") is True


def test_internal_rag_routing_detects_internal_person_question_without_company_keyword():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("Wer ist Engin Bayir?") is True
    assert looks_internal("Was weißt du über Thomas Keller?") is True
    assert looks_internal("Und wer ist Leonie Keller?") is True


def test_documented_short_alias_uses_internal_rag_instead_of_time_tool():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("TD?") is True
    assert looks_internal("VK in NIE?") is True


def test_internal_rag_routing_does_not_block_drafting_from_user_supplied_facts():
    looks_internal = load_rag_routing_helpers()

    request = (
        "Verfasse eine E-Mail an Herrn Friedrich-Kahle. Der Tagesabschluss soll "
        "optimiert werden. Aktuell werden Belege über den Tag gescannt und an "
        "eine Teams-Gruppe gesendet. Schlage als Idee einen zusätzlichen Button "
        "für debitorenbuchhaltung@kahle.de vor und kennzeichne technische "
        "Machbarkeit ausdrücklich als noch zu prüfen."
    )

    assert looks_internal(request) is False


def test_internal_rag_routing_keeps_internal_factual_research_for_drafts():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal(
        "Schreibe einen Text darüber, warum VaudisX bei KAHLE ein gutes DMS ist."
    ) is True


def test_prerouted_rag_tool_output_keeps_native_function_call_visible():
    helper = load_function_from_middleware("_prerouted_rag_tool_output")

    started = helper("call-1", "Wer ist Thomas Keller?", completed=False)
    completed = helper("call-1", "Wer ist Thomas Keller?", completed=True)

    assert started == [{
        "type": "function_call",
        "id": "call-1",
        "call_id": "call-1",
        "name": "rag_chat",
        "arguments": '{"query": "Wer ist Thomas Keller?"}',
        "status": "in_progress",
    }]
    assert completed[0]["status"] == "completed"
    assert completed[1]["type"] == "function_call_output"
    assert completed[1]["call_id"] == "call-1"


def test_prerouted_rag_status_is_hidden_for_personio_only_plan():
    try:
        should_emit = load_function_from_middleware("_should_emit_prerouted_rag_status")
    except (KeyError, StopIteration):
        pytest.fail("middleware must decide whether a RAG status is actually required")

    assert should_emit(retrieval_plan("Wo arbeitet Max Mustermann?")) is False
    assert should_emit(retrieval_plan("Was sagt unsere interne Richtlinie?")) is True


def test_prerouted_rag_answer_stream_is_not_suppressed_after_evidence_is_ready():
    helper = load_function_from_middleware("_should_suppress_initial_rag_response")

    assert helper(
        rag_tool_available=True,
        internal_rag_required=True,
        prerouted=True,
    ) is False
    assert helper(
        rag_tool_available=True,
        internal_rag_required=True,
        prerouted=False,
    ) is True


def test_general_vinci_models_redirect_mail_drafting_to_mailer():
    redirect = load_mail_redirect_helper()
    request = "Bitte schreibe eine E-Mail an einen Kunden wegen der langen Wartezeit."

    for model in (
        {"id": "vinci-2-clone-clone-clone", "name": "KAHLE-Vinci"},
        {"id": "kahle-vinci-thinking", "name": "KAHLE-Vinci-Thinking"},
        {"id": "kahle-vinci-max-thinking", "name": "KAHLE-Vinci-Max-Thinking"},
        {"id": "kahle-vinci-future", "name": "KAHLE-Vinci-Future"},
    ):
        assert "Mailer-Vinci" in redirect(model, request)

    assert redirect(
        {"id": "kahle-email-vinci", "name": "Mailer-Vinci"}, request
    ) == ""
    assert redirect(
        {"id": "kahle-vinci-thinking", "name": "KAHLE-Vinci-Thinking"},
        "Was ist bei KAHLE zur E-Mail-Archivierung geregelt?",
    ) == ""


def test_general_vinci_redirects_mail_draft_even_when_internal_evidence_is_requested():
    redirect = load_mail_redirect_helper()

    assert "Mailer-Vinci" in redirect(
        {"id": "kahle-vinci-max-thinking", "name": "KAHLE-Vinci-Max-Thinking"},
        "Suche im internen Wissen und schreibe danach eine E-Mail an den Kunden.",
    )


def test_mailer_first_turn_returns_four_contextual_questions_without_a_draft():
    initial_response = load_mailer_initial_question_helper()
    request = (
        "Verfasse eine Mail an Herrn Friedrich-Kahle mit der Frage, ob der "
        "Tagesabschluss optimiert werden kann. Technische Fehler und Scanmodi "
        "stoeren den Ablauf. Als Idee soll ein direkter Versand an die "
        "Debitorenbuchhaltung geprueft werden."
    )

    response = initial_response(
        {"id": "kahle-email-vinci", "name": "Mailer-Vinci"},
        [{"role": "user", "content": request}],
    )

    assert response == (
        "Bevor ich den Entwurf schreibe, brauche ich noch diese vier Angaben:\n\n"
        "1. Welche konkrete Entscheidung oder Reaktion soll Herr Friedrich-Kahle "
        "nach der Mail geben?\n"
        "2. Welche Aussagen zur technischen Machbarkeit sind bereits bestätigt "
        "und was ist bisher nur ein Vorschlag?\n"
        "3. Welcher nächste Schritt oder Termin soll in der Mail verbindlich "
        "vorgeschlagen werden?\n"
        "4. Ist die Mail intern oder extern und soll sie formell oder informell "
        "geschrieben sein?"
    )
    assert "Betreff:" not in response


def test_mailer_asks_whether_a_pasted_mail_should_be_answered_or_improved():
    initial_response = load_mailer_initial_question_helper()
    response = initial_response(
        {"id": "kahle-email-vinci", "name": "Mailer-Vinci"},
        [{"role": "user", "content": "Hallo Herr Müller,\n\nich sende Ihnen den Zwischenstand.\n\nViele Grüße\nJan"}],
    )

    assert "Soll ich auf diese Mail antworten oder deinen Entwurf verbessern?" in response
    assert "1." in response and "4." in response


def test_mailer_question_gate_runs_only_before_the_first_assistant_reply():
    initial_response = load_mailer_initial_question_helper()
    model = {"id": "kahle-email-vinci", "name": "Mailer-Vinci"}

    assert initial_response(
        model,
        [
            {"role": "user", "content": "Schreibe eine Mail an einen Kunden."},
            {"role": "assistant", "content": "1. Was soll die Mail erreichen?"},
            {"role": "user", "content": "Er soll einen neuen Termin bestaetigen."},
        ],
    ) == ""
    assert initial_response(
        {"id": "kahle-vinci-thinking", "name": "KAHLE-Vinci-Thinking"},
        [{"role": "user", "content": "Schreibe eine Mail an einen Kunden."}],
    ) == ""


def test_mailer_answers_to_initial_questions_do_not_become_internal_rag_queries():
    uses_supplied_context = load_mailer_followup_routing_helper()
    model = {"id": "kahle-email-vinci", "name": "Mailer-Vinci"}
    messages = [
        {"role": "user", "content": "Verfasse eine interne Mail zu unserem Scanprozess."},
        {
            "role": "assistant",
            "content": "Bevor ich den Entwurf schreibe, brauche ich noch diese vier Angaben:\n\n1. Ziel?",
        },
        {
            "role": "user",
            "content": (
                "1. Wir duerfen den Prozess anpassen. 2. Scanner koennen individuelle "
                "Buttons nutzen. 3. Test an einem Standort. 4. intern und formell."
            ),
        },
    ]

    assert uses_supplied_context(model, messages, messages[-1]["content"]) is True
    assert uses_supplied_context(
        model,
        messages[:-1] + [{"role": "user", "content": "Suche im internen Wissen nach der Scanrichtlinie."}],
        "Suche im internen Wissen nach der Scanrichtlinie.",
    ) is False


def test_prerouted_generic_opening_hours_keeps_clarification_answer():
    outcome = load_function_from_middleware("_internal_rag_source_outcome")
    clarification = load_function_from_middleware("_internal_rag_clarification")
    sources = [{
        "source": {"name": "rag_chat/rag_chat"},
        "document": [
            "KAHLE_RAG_RESULT\nFOUND: false\n"
            "CLARIFICATION_REQUIRED: true\n"
            "ANSWER: Für welchen Standort brauchst du die Öffnungszeiten?"
        ],
    }]

    assert outcome(sources) == "clarification"
    assert clarification(sources) == (
        "Für welchen Standort brauchst du die Öffnungszeiten?"
    )


def test_opening_hours_clarification_followup_is_internal_rag_request():
    helper = load_function_from_middleware("_is_internal_clarification_followup")
    messages = [
        {"role": "user", "content": "Wie sind unsere Öffnungszeiten?"},
        {
            "role": "assistant",
            "content": (
                "Für welchen Standort und welchen Bereich (Verkauf, Service oder "
                "Teiledienst) brauchst du die Öffnungszeiten?"
            ),
        },
        {"role": "user", "content": "allgemein alles"},
    ]

    assert helper(messages, "allgemein alles") is True


def test_opening_hours_followup_expands_to_one_complete_rag_query():
    helper = load_function_from_middleware("_expanded_internal_rag_query")
    messages = [
        {"role": "user", "content": "Wie sind unsere Öffnungszeiten?"},
        {
            "role": "assistant",
            "content": (
                "Für welchen Standort und welchen Bereich (Verkauf, Service oder "
                "Teiledienst) brauchst du die Öffnungszeiten?"
            ),
        },
        {"role": "user", "content": "allgemein alles"},
    ]

    expanded = helper(messages, "allgemein alles")

    assert expanded.startswith("Öffnungszeiten Verkauf Service Teiledienst")
    for location in (
        "Hannover", "Wunstorf", "Wedemark", "Walsrode",
        "Neustadt am Rübenberge", "Nienburg", "Stadthagen",
    ):
        assert location in expanded


def test_opening_hours_abbreviation_followup_expands_before_routing():
    expand = load_function_from_middleware("_expanded_internal_rag_query")
    is_followup = load_function_from_middleware("_is_internal_clarification_followup")
    messages = [
        {"role": "user", "content": "Wie sind unsere Öffnungszeiten?"},
        {
            "role": "assistant",
            "content": (
                "Für welchen Standort und welchen Bereich (Verkauf, Service oder "
                "Teiledienst) brauchst du die Öffnungszeiten?"
            ),
        },
        {"role": "user", "content": "TD in NIE"},
    ]

    expanded = expand(messages, "TD in NIE")

    assert expanded == "Teiledienst in Nienburg"
    assert is_followup(messages, expanded) is True


def test_customer_lock_marketing_followup_keeps_clarification_context():
    helper = load_function_from_middleware("_expanded_internal_rag_query")
    messages = [
        {"role": "user", "content": "Wie sperre ich einen Kunden in Vaudis?"},
        {
            "role": "assistant",
            "content": (
                "Geht es darum, Werbung und Befragungen für den Kunden zu sperren, "
                "oder um eine allgemeine Kundensperre in Vaudis?"
            ),
        },
        {"role": "user", "content": "Werbung"},
    ]

    assert helper(messages, "Werbung") == (
        "Wie sperre ich Werbung und automatisierte Befragungen für einen Kunden "
        "in Vaudis über die DSE-Kontaktfreigaben?"
    )


def test_customer_lock_general_followup_keeps_clarification_context():
    helper = load_function_from_middleware("_expanded_internal_rag_query")
    messages = [
        {"role": "user", "content": "Wie sperre ich einen Kunden in Vaudis?"},
        {
            "role": "assistant",
            "content": (
                "Geht es darum, Werbung und Befragungen für den Kunden zu sperren, "
                "oder um eine allgemeine Kundensperre in Vaudis?"
            ),
        },
        {"role": "user", "content": "allgemeine Sperre"},
    ]

    assert helper(messages, "allgemeine Sperre") == (
        "Wie veranlasse ich eine allgemeine Kundensperre in Vaudis? Falls dafür "
        "keine freigegebene Anleitung vorliegt: Welche freigegebene "
        "Datenschutz-Anlaufstelle nennt das KAHLE-Wissen für Sperranfragen?"
    )


@pytest.mark.parametrize(
    "followup",
    [
        "allgemein",
        "Ich meine eine allgemeine Kundensperre",
        "Ich meine eine allgemeine Kundensperre in Vaudis, nicht den Werbewiderspruch.",
    ],
)
def test_customer_lock_general_followup_variants_resolve_identically(followup):
    helper = load_function_from_middleware("_expanded_internal_rag_query")
    messages = [
        {"role": "user", "content": "Wie sperre ich einen Kunden bei KAHLE?"},
        {
            "role": "assistant",
            "content": (
                "Geht es darum, Werbung und Befragungen für den Kunden zu sperren, "
                "oder um eine allgemeine Kundensperre in Vaudis?"
            ),
        },
        {"role": "user", "content": followup},
    ]

    assert helper(messages, followup) == (
        "Wie veranlasse ich eine allgemeine Kundensperre in Vaudis? Falls dafür "
        "keine freigegebene Anleitung vorliegt: Welche freigegebene "
        "Datenschutz-Anlaufstelle nennt das KAHLE-Wissen für Sperranfragen?"
    )


def test_customer_lock_general_followup_uses_prior_user_question_if_clarification_content_is_structured():
    helper = load_function_from_middleware("_expanded_internal_rag_query")
    messages = [
        {"role": "user", "content": "Wie sperre ich einen Kunden bei KAHLE?"},
        {"role": "assistant", "content": [{"type": "text", "text": "Klärungsfrage"}]},
        {"role": "user", "content": "allgemein"},
    ]

    assert helper(messages, "allgemein") == (
        "Wie veranlasse ich eine allgemeine Kundensperre in Vaudis? Falls dafür "
        "keine freigegebene Anleitung vorliegt: Welche freigegebene "
        "Datenschutz-Anlaufstelle nennt das KAHLE-Wissen für Sperranfragen?"
    )


def test_customer_lock_clarification_names_marketing_locations_and_other_site_scope():
    tool_path = ROOT / "open-webui-tools" / "rag_chat_hybrid_tool.py"
    tree = ast.parse(tool_path.read_text(encoding="utf-8"))
    node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_clarification_for_query"
    )
    module_ast = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module_ast)
    namespace = {"re": re}
    exec(compile(module_ast, str(tool_path), "exec"), namespace)

    assert namespace["_clarification_for_query"]("Wie sperre ich einen Kunden bei KAHLE?") == (
        "Geht es darum, Werbung und Befragungen für den Kunden in Hannover, Wunstorf oder Wedemark zu sperren, "
        "oder um eine allgemeine Kundensperre in Vaudis für einen anderen Standort?"
    )


def test_person_system_followup_keeps_named_person_relation():
    helper = load_function_from_middleware("_expanded_internal_rag_query")
    messages = [
        {"role": "user", "content": "Wer ist Stefan Schrader?"},
        {"role": "assistant", "content": "Stefan Schrader ist Ansprechpartner für IT/EDV [Quelle 1]."},
        {"role": "user", "content": "Und was hat er mit Vaudis zu tun?"},
    ]

    assert helper(messages, messages[-1]["content"]) == (
        "Welche belegte Zuständigkeit oder Beziehung hat Stefan Schrader zu Vaudis?"
    )


def test_person_contact_followup_keeps_the_prior_explicit_person_question():
    helper = load_function_from_middleware("_expanded_internal_rag_query")
    messages = [
        {"role": "user", "content": "Wer ist Erika Beispiel?"},
        {"role": "assistant", "content": "Aktueller Personio-Treffer."},
        {"role": "user", "content": "Wie kann ich ihn erreichen?"},
    ]

    assert helper(messages, messages[-1]["content"]) == (
        "Wie kann ich ihn erreichen?\nWer ist Erika Beispiel?"
    )


def test_internal_rag_routing_does_not_treat_internet_as_intern():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("Bitte recherchiere wie Spaghetti hergestellt werden im Internet") is False


def test_internal_rag_routing_does_not_auto_route_raw_mail_drafts():
    looks_internal = load_rag_routing_helpers()

    raw_mail = """Hallo Herr Langhorst,

ich habe die beiden weiteren DA-Center soweit vorbereitet mit den Daten, die ich habe.
Ich benoetige letztlich noch jeweils die Dokumenten-ID fuer die CSV-Datei.

Fuer Walsrode finde ich aber keinen einzigen Termin in CATCH.

Viele Gruesse
Jan"""

    assert looks_internal(raw_mail) is False


def test_internal_rag_routing_does_not_auto_route_raw_mail_without_signoff():
    looks_internal = load_rag_routing_helpers()

    raw_mail = """Hallo Herr Langhorst,
ich habe die beiden weiteren DA-Center soweit vorbereitet mit den Daten, die ich habe.
Ich benoetige letztlich noch jeweils die Dokumenten-ID fuer die CSV-Datei,
die fuer das jeweilige Center abgerufen werden soll aus dem GUDAT-System.
Fuer Walsrode finde ich aber keinen einzigen Termin in CATCH.
Das liegt vermutlich daran, dass die abgerufene Quelldatei gudat_4357.csv 12 Spalte hat."""

    assert looks_internal(raw_mail) is False


def test_internal_rag_routing_does_not_auto_route_answer_mail_command_with_raw_mail():
    looks_internal = load_rag_routing_helpers()

    raw_mail = """Beantworte die Mail:
Hallo Herr Langhorst,
ich habe die beiden weiteren DA-Center soweit vorbereitet mit den Daten, die ich habe.
Ich benoetige letztlich noch jeweils die Dokumenten-ID fuer die CSV-Datei.
Fuer Walsrode finde ich aber keinen einzigen Termin in CATCH."""

    assert looks_internal(raw_mail) is False


def test_internal_rag_routing_still_detects_explicit_internal_policy_questions():
    looks_internal = load_rag_routing_helpers()

    assert looks_internal("Was sagt unsere interne Richtlinie zur Nutzung von Kundendaten in Mails?") is True


def test_native_function_calling_cannot_bypass_internal_rag():
    fallback = load_native_rag_fallback()

    calls = fallback(
        {"rag_chat": object()},
        "Was sagt unsere interne Richtlinie zur Nutzung von Kundendaten?",
        [],
        [{"type": "message", "content": [{"type": "output_text", "text": "Geraten"}]}],
    )

    assert calls[0][0]["function"]["name"] == "rag_chat"
    assert "interne Richtlinie" in calls[0][0]["function"]["arguments"]


def test_native_rag_fallback_does_not_repeat_after_tool_result():
    fallback = load_native_rag_fallback()

    assert fallback(
        {"rag_chat": object()},
        "Was sagt unsere interne Richtlinie?",
        [],
        [{"type": "function_call_output"}],
    ) == []


def test_canonical_source_link_replaces_model_invented_host():
    helpers = load_canonical_rag_source_helpers()
    tool_result = (
        'KAHLE_RAG_RESULT\nFOUND: true\nSOURCES_JSON: '
        '[{"title":"Policy","source_url":"/wissen/api/portal/sources/v1"}]\n'
        'FEEDBACK_LINK: x'
    )
    sources = helpers["_extract_kahle_rag_sources"](tool_result)
    output = [{
        "type": "message",
        "content": [{
            "type": "output_text",
            "text": "Details: [Policy](https://kahle.wissen/api/portal/sources/v1)",
        }],
    }]

    helpers["_append_canonical_rag_source_links"](output, sources)

    text = output[0]["content"][0]["text"]
    assert "https://kahle.wissen" not in text
    assert "[Policy](/wissen/api/portal/sources/v1)" in text


def test_canonical_source_link_replaces_existing_model_source_section_once():
    helpers = load_canonical_rag_source_helpers()
    sources = [{
        "title": "Policy",
        "source_url": "/wissen/api/portal/sources/v1",
    }]
    output = [{
        "type": "message",
        "content": [{
            "type": "output_text",
            "text": (
                "Die belegte Antwort [1].\n\n"
                "Quellen:\n- [Policy](/wissen/api/portal/sources/v1)"
            ),
        }],
    }]

    helpers["_append_canonical_rag_source_links"](output, sources)

    text = output[0]["content"][0]["text"]
    assert text.count("Quellen:") == 1
    assert text.count("[Policy](/wissen/api/portal/sources/v1)") == 1


def test_canonical_rag_source_event_names_the_document_instead_of_the_tool():
    helpers = load_canonical_rag_source_helpers()
    sources = [{
        "title": "WPS Bedienungsanleitung",
        "source_url": "/wissen/api/portal/sources/version-1",
        "document_id": "doc-1",
        "version_id": "version-1",
        "knowledgebase_ids": ["kb-service"],
        "evidence_text": "Terminmaske öffnen und Kunden auswählen.",
    }]

    events = helpers["_canonical_kahle_rag_source_events"](sources)

    assert events == [{
        "source": {
            "name": "WPS Bedienungsanleitung",
            "url": "/wissen/api/portal/sources/version-1",
        },
        "document": ["Terminmaske öffnen und Kunden auswählen."],
        "metadata": [{
            "document_id": "doc-1",
            "version_id": "version-1",
            "knowledgebase_ids": ["kb-service"],
            "source": "WPS Bedienungsanleitung",
            "url": "/wissen/api/portal/sources/version-1",
        }],
    }]


def test_canonical_feedback_link_replaces_plain_model_text_with_clickable_portal_link():
    helpers = load_canonical_rag_feedback_helpers()
    tool_result = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "FEEDBACK_LINK: [Wissensfehler melden](/wissen/?feedback=1&chat_id=chat-1&message_id=msg-1)"
    )
    link = helpers["_extract_kahle_rag_feedback_link"](tool_result)
    output = [{
        "type": "message",
        "content": [{"type": "output_text", "text": "Die Antwort.\n\nWissensfehler melden"}],
    }]

    helpers["_append_canonical_rag_feedback_link"](output, link)

    assert output[0]["content"][0]["text"] == (
        "Die Antwort.\n\n"
        "[Wissensfehler melden](/wissen/?feedback=1&chat_id=chat-1&message_id=msg-1)"
    )


def test_canonical_feedback_link_accepts_transition_links_with_source_references():
    helpers = load_canonical_rag_feedback_helpers()
    tool_result = (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        "FEEDBACK_LINK: [Wissensfehler melden]"
        "(/wissen/?feedback=1&chat_id=chat-1&message_id=msg-1"
        "&document_ids=doc-1%2Cdoc-2&knowledgebase_ids=kb-service)"
    )
    link = helpers["_extract_kahle_rag_feedback_link"](tool_result)
    assert link.endswith("&knowledgebase_ids=kb-service")


def test_last_kahle_answer_text_reads_only_the_final_message_output():
    helper = load_function_from_middleware("_last_kahle_answer_text")
    output = [
        {"type": "reasoning", "content": [{"type": "output_text", "text": "intern"}]},
        {"type": "message", "content": [{"type": "output_text", "text": "Antwort eins"}]},
        {"type": "message", "content": [{"type": "output_text", "text": "Antwort zwei "}]},
    ]

    assert helper(output) == "Antwort zwei"


def test_active_harness_records_validation_without_generating_replacement_answer():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "validate_knowledge_harness_answer(" in source
    assert "validation.retry_prompt()" not in source
    assert "retry_form_data" not in source
    assert "metadata['kahle_answer_validation']" in source
    assert "'kahle_answer_validation': metadata['kahle_answer_validation']" in source


def test_realtime_chat_save_persists_harness_validation_and_metrics_server_side():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    realtime_block = source[source.index("realtime_metadata = {") :]
    realtime_block = realtime_block[: realtime_block.index("# Send a webhook notification")]

    assert "'kahle_answer_validation': metadata['kahle_answer_validation']" in realtime_block
    assert "'kahle_harness_metrics': metadata['kahle_harness_metrics']" in realtime_block
    assert "{'done': True, **realtime_metadata}" in realtime_block


def test_active_harness_answer_stream_timeout_ends_a_never_finishing_stream():
    helper = load_function_from_middleware("_await_kahle_answer_stream")

    async def never_finishes():
        await asyncio.Event().wait()

    assert asyncio.run(helper(never_finishes(), timeout_seconds=0.01)) is True


def test_active_harness_timeout_is_wired_to_a_safe_visible_delivery_state():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "_knowledge_harness_answer_timeout_seconds()" in source
    assert source.count("_await_kahle_answer_stream(") >= 2
    assert "metadata['kahle_answer_stream_timed_out'] = True" in source
    assert "'safe_timeout_fallback'" in source


def load_fallback_tool_helpers():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {
        "_ascii_fold",
        "_infer_generated_file_output_format",
        "_looks_like_previous_result_file_request",
        "_infer_fallback_tool_calls",
    }
    nodes = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Any": Any,
        "Optional": Optional,
        "re": re,
        "unicodedata": unicodedata,
        "tools": {"kahle_workflow_execute": object()},
        "attached_file_names": [],
        "attached_exact_paths": [],
        "_looks_like_internal_rag_request": lambda text: False,
    }
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_infer_fallback_tool_calls"]


def test_previous_result_word_request_routes_to_workflow_before_streaming():
    infer_fallback = load_fallback_tool_helpers()

    calls = infer_fallback(
        {},
        "Bitte gib mir das Ergebnis einmal strukturiert als WOrd aus",
    )

    assert calls == [
        {
            "name": "kahle_workflow_execute",
            "parameters": {
                "auftrag": "Bitte gib mir das Ergebnis einmal strukturiert als WOrd aus",
                "output_format": "docx",
            },
        }
    ]


def test_direct_word_creation_request_routes_to_workflow_before_streaming():
    infer_fallback = load_fallback_tool_helpers()

    calls = infer_fallback(
        {},
        (
            "Erstelle eine Word-Datei mit der Ueberschrift KAHLE-Vinci Migrationstest "
            "und einem kurzen Absatz, dass die Servermigration erfolgreich geprueft wurde."
        ),
    )

    assert calls == [
        {
            "name": "kahle_workflow_execute",
            "parameters": {
                "auftrag": (
                    "Erstelle eine Word-Datei mit der Ueberschrift KAHLE-Vinci Migrationstest "
                    "und einem kurzen Absatz, dass die Servermigration erfolgreich geprueft wurde."
                ),
                "output_format": "docx",
            },
        }
    ]


def load_stream_safe_output():
    tree = ast.parse(MIDDLEWARE.read_text(encoding="utf-8"))
    wanted = {"_strip_pseudo_toolcall_stream_text", "_stream_safe_output"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"copy": copy, "re": re}
    exec(compile(module, str(MIDDLEWARE), "exec"), namespace)
    return namespace["_stream_safe_output"]


def test_stream_safe_output_hides_visible_pseudo_toolcall_text():
    stream_safe_output = load_stream_safe_output()
    output = [
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": 'Ich erstelle die Datei.[TOOL_CALLS]kahle_workflow_execute{"output_format":"docx"}',
                }
            ],
        }
    ]

    safe = stream_safe_output(output)

    assert safe[0]["content"][0]["text"] == "Ich erstelle die Datei."
    assert output[0]["content"][0]["text"].startswith("Ich erstelle die Datei.[TOOL_CALLS]")


def test_stream_safe_output_blanks_thinking_model_json_toolcall():
    """kahle-vinci-thinking (Responses API) emits a reasoning item followed by a
    message item whose text is a pretty-printed JSON tool call. The stream-safe
    view (used for both streaming and the final `done` emit) must blank that
    message text so the raw block never reaches the browser, while leaving the
    underlying output untouched so the outlet guard can still recover."""
    stream_safe_output = load_stream_safe_output()
    output = [
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Thought"}]},
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": '\n{\n  "tool": "safe_webcaller",\n  "parameters": {"query": "Elektroauto 2026"}\n}',
                }
            ],
        },
    ]

    safe = stream_safe_output(output)

    assert safe[1]["content"][0]["text"] == ""
    # Original output is preserved (deepcopy) so the guard still sees the leak.
    assert "safe_webcaller" in output[1]["content"][0]["text"]


def test_stream_safe_output_hides_unsupported_initial_internal_answer():
    stream_safe_output = load_stream_safe_output()
    output = [
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": "Um einen Termin im WPS zu planen, folge diesen erfundenen Schritten.",
                }
            ],
        }
    ]

    safe = stream_safe_output(output, suppress_message_text=True)

    assert safe[0]["content"][0]["text"] == ""
    assert "erfundenen Schritten" in output[0]["content"][0]["text"]


def test_stream_safe_output_hides_thinking_reasoning_for_unsupported_internal_answer():
    stream_safe_output = load_stream_safe_output()
    output = [
        {
            "type": "reasoning",
            "summary": [
                {
                    "type": "summary_text",
                    "text": "No internal result, so I will answer from general knowledge.",
                }
            ],
        },
        {
            "type": "message",
            "content": [{"type": "output_text", "text": "Erfundene WPS-Anleitung"}],
        },
    ]

    safe = stream_safe_output(output, suppress_message_text=True)

    assert safe[0]["summary"][0]["text"] == ""
    assert safe[1]["content"][0]["text"] == ""


def test_native_internal_rag_suppression_is_wired_before_initial_stream():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "force_internal_rag = (" in source
    assert "if force_internal_rag:" in source
    assert "pre_route_tools = {'rag_chat': tools_dict['rag_chat']}" in source
    assert "form_data, flags = await chat_completion_tools_handler(" in source
    assert "_should_suppress_initial_rag_response(" in source
    assert "prerouted=bool(metadata.get('kahle_internal_rag_prerouted'))" in source
    assert "return _stream_safe_output(" in source
    assert "suppress_message_text=suppress_initial_rag_response" in source
    assert "suppress_initial_rag_response = False" in source


def test_prerouted_rag_receives_information_needs_in_its_copied_metadata():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    block = source[
        source.index("async def retrieve_pre_route_rag()"):
        source.index("retrieval = await _execute_kahle_retrieval_plan(")
    ]

    assert "pre_route_metadata = pre_route_form_data.setdefault('metadata', {})" in block
    assert "pre_route_metadata['_kahle_information_needs']" in block


def test_prerouted_rag_is_not_exposed_to_native_model_for_a_second_call():
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "native_tools_dict =" in source
    assert "name == 'rag_chat'" in source
    assert "metadata.get('kahle_mailer_drafting_followup')" in source
    assert "or (force_internal_rag and pre_routed_internal_rag)" in source


def test_prerouted_rag_replaces_generic_tool_source_even_without_documents():
    source = MIDDLEWARE.read_text(encoding="utf-8")
    block = source[source.index("canonical_pre_route_events =") :]
    block = block[: block.index("if pre_routed_internal_rag:")]

    assert "sources[:] = [" in block
    assert "if 'rag_chat' not in str(" in block
    assert block.index("sources[:] = [") < block.index("if canonical_pre_route_events:")


if __name__ == "__main__":
    test_internal_rag_routing_detects_recovery_gutschein()
    test_internal_rag_routing_does_not_treat_internet_as_intern()
    test_internal_rag_routing_does_not_auto_route_raw_mail_drafts()
    test_internal_rag_routing_does_not_auto_route_raw_mail_without_signoff()
    test_internal_rag_routing_does_not_auto_route_answer_mail_command_with_raw_mail()
    test_internal_rag_routing_still_detects_explicit_internal_policy_questions()
    test_previous_result_word_request_routes_to_workflow_before_streaming()
    test_stream_safe_output_hides_visible_pseudo_toolcall_text()
    print("middleware internal rag routing tests passed")
