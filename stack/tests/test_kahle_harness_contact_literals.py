"""Contact literals quoted verbatim in approved RAG evidence are bound to it.

Decision 2026-09-30: besides typed functional-contact rows, a contact value
that appears word for word in a supported RAG claim of the current request may
be named, cited with that claim's source. Values outside the evidence stay
unbound.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "open-webui-overrides" / "open_webui" / "utils" / "kahle_knowledge_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("kahle_harness_contact_literals", HARNESS)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _rag_result(*claim_texts):
    claims = [
        {
            "claim_id": f"R1C{index}",
            "source_id": "#1",
            "text": text,
            "evidence_span": text,
            "document_id": "doc-1",
            "version_id": "v-1",
            "evidence_role": "editorial",
        }
        for index, text in enumerate(claim_texts, 1)
    ]
    bundle = {
        "schema_version": "kahle.evidence-bundle.v1",
        "status": "supported",
        "supported_claims": claims,
        "missing_information": [],
        "conflicts": [],
        "sources": [{"number": 1, "document_id": "doc-1", "version_id": "v-1", "title": "Prozess"}],
    }
    return (
        "KAHLE_RAG_RESULT\nFOUND: true\n"
        f"EVIDENCE_BUNDLE_JSON: {json.dumps(bundle, ensure_ascii=False)}\n"
        "CONTEXT:\n[1] Prozess | A\n" + " ".join(claim_texts) + "\n"
    )


def _decision(harness, rag, query="Wie hinterlege ich einen Werbewiderspruch am Standort Walsrode?"):
    return harness.build_result_driven_decision(
        called_tools=("rag_chat",),
        query=query,
        messages=[],
        model_id="m",
        permission_scope={"user_id": "u"},
        rag_result=rag,
    )


def test_contact_in_evidence_text_becomes_a_source_bound_contact():
    harness = load_harness()
    decision = _decision(harness, _rag_result(
        "An allen anderen Standorten wende dich an datenschutz@kahle.de.",
        "Die IT erreichst du über https://ticket.kahle.de/login.php.",
    ))

    bindings = decision.answer_contract.allowed_contact_bindings
    assert {(item["channel"], item["value"], item["source_id"]) for item in bindings} == {
        ("email", "datenschutz@kahle.de", "#1"),
        ("url", "https://ticket.kahle.de/login.php", "#1"),
    }
    assert all(item["binding"] == "evidence_text" for item in bindings)
    assert "datenschutz@kahle.de" in decision.answer_contract.allowed_contact_values


def test_answer_quoting_an_evidence_contact_passes_validation():
    harness = load_harness()
    decision = _decision(harness, _rag_result(
        "An allen anderen Standorten wende dich an datenschutz@kahle.de.",
    ))

    result = harness.validate_answer(
        "Für alle anderen Standorte wende dich an datenschutz@kahle.de [1].",
        decision.to_dict(),
    )

    assert "unbound_contact_literal" not in [item["code"] for item in result.violations]
    assert result.status == "accepted"


def test_contact_outside_the_evidence_stays_blocked():
    harness = load_harness()
    decision = _decision(harness, _rag_result(
        "An allen anderen Standorten wende dich an datenschutz@kahle.de.",
    ))

    result = harness.validate_answer(
        "Schreib an datenschutz@kahle.de [1] oder an info@kahle.de [1].",
        decision.to_dict(),
    )

    assert [item["code"] for item in result.violations] == ["unbound_contact_literal"]
    assert result.retry_required


def test_contract_explains_that_evidence_quotes_may_be_named():
    harness = load_harness()
    # A neutral query: the opt-out scope case uses its own location contract.
    decision = _decision(
        harness, _rag_result("Kontakt: datenschutz@kahle.de."),
        query="Wie erreiche ich den Datenschutz?",
    )

    assert "Kontaktwerte, die wörtlich in einer belegten Aussage stehen" in decision.answer_prompt()


def _preroute_decision(harness, rag, query="Wie hinterlege ich einen Werbewiderspruch in Vaudis?"):
    return harness.build_decision(
        query=query,
        resolved_query=query,
        messages=[],
        model_id="m",
        permission_scope={"user_id": "u"},
        rag_result=rag,
    )


def test_preroute_contract_binds_evidence_contacts_without_a_contact_question():
    harness = load_harness()
    decision = _preroute_decision(harness, _rag_result(
        "An allen anderen Standorten wende dich an datenschutz@kahle.de.",
    ))

    assert "datenschutz@kahle.de" in decision.answer_contract.allowed_contact_values
    assert {item["binding"] for item in decision.answer_contract.allowed_contact_bindings} == {"evidence_text"}
    result = harness.validate_answer(
        "Für alle anderen Standorte wende dich an datenschutz@kahle.de [1].",
        decision.to_dict(),
    )
    assert "unbound_contact_literal" not in [item["code"] for item in result.violations]


def test_preroute_contract_keeps_person_contacts_out():
    harness = load_harness()
    decision = _preroute_decision(harness, _rag_result(
        "Ansprechpartnerin ist Anna Beispiel, erreichbar unter anna.beispiel@kahle.de.",
    ))

    assert "anna.beispiel@kahle.de" not in decision.answer_contract.allowed_contact_values
