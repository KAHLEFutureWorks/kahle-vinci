from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTER = ROOT.parent / "scripts" / "openwebui" / "kahle-harness-acceptance.py"
MATRIX = ROOT.parent / "scripts" / "openwebui" / "kahle-harness-acceptance-matrix.json"


def load_reporter():
    spec = importlib.util.spec_from_file_location("kahle_harness_acceptance", REPORTER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_acceptance_report_distinguishes_passed_unavailable_and_not_authorized():
    reporter = load_reporter()
    runs = [
        {
            "case_id": "person_lookup",
            "profile": "employee",
            "answer": "Thomas Keller ist Geschäftsführer [1].\n\nWissensfehler melden",
            "metrics": {
                "model_name": "KAHLE-Vinci",
                "intent_kind": "employee_directory",
                "tool_called": "rag_chat",
                "evidence_status": "supported",
                "source_count": 1,
                "permission_scope_present": True,
                "final_validation_status": "accepted",
                "feedback_link_present": True,
                "latency_ms": 2049,
            },
        },
        {
            "case_id": "person_lookup",
            "profile": "employee",
            "answer": "Thomas Keller ist Mitglied der Geschäftsführung [1].\n\nWissensfehler melden",
            "metrics": {
                "model_name": "KAHLE-Vinci-Thinking",
                "intent_kind": "employee_directory",
                "tool_called": "rag_chat",
                "evidence_status": "supported",
                "source_count": 1,
                "permission_scope_present": True,
                "final_validation_status": "accepted",
                "feedback_link_present": True,
                "latency_ms": 6529,
            },
        },
    ]

    report = reporter.build_acceptance_report(
        runs,
        expected_models=(
            "KAHLE-Vinci",
            "KAHLE-Vinci-Thinking",
            "KAHLE-Vinci-Max-Thinking",
        ),
        profile_authorization={"employee": True, "manager": False},
        required_case_ids=("person_lookup",),
    )

    assert report["schema_version"] == "kahle.harness-acceptance-report.v1"
    assert report["summary"] == {
        "passed": 2,
        "failed": 0,
        "unavailable": 1,
        "not_authorized": 3,
    }
    statuses = {
        (entry["model_name"], entry["profile"]): entry["status"]
        for entry in report["coverage"]
    }
    assert statuses[("KAHLE-Vinci", "employee")] == "passed"
    assert statuses[("KAHLE-Vinci-Thinking", "employee")] == "passed"
    assert statuses[("KAHLE-Vinci-Max-Thinking", "employee")] == "unavailable"
    assert statuses[("KAHLE-Vinci", "manager")] == "not_authorized"
    assert report["metrics"]["latency_p50_ms"] == 2049
    assert report["metrics"]["latency_p95_ms"] == 6529


def test_acceptance_report_fails_available_model_when_required_cases_are_missing():
    reporter = load_reporter()
    run = {
        "case_id": "person_lookup",
        "profile": "employee",
        "answer": "Belegte Antwort [1].\n\nWissensfehler melden",
        "metrics": {
            "model_name": "KAHLE-Vinci",
            "intent_kind": "employee_directory",
            "tool_called": "rag_chat",
            "evidence_status": "supported",
            "source_count": 1,
            "permission_scope_present": True,
            "final_validation_status": "accepted",
            "feedback_link_present": True,
            "latency_ms": 2000,
        },
    }

    report = reporter.build_acceptance_report(
        [run],
        expected_models=("KAHLE-Vinci",),
        profile_authorization={"employee": True},
        required_case_ids=("person_lookup", "procedure_missing_guide"),
    )

    assert report["summary"]["failed"] == 1
    assert report["coverage"][0]["status"] == "failed"
    assert report["coverage"][0]["reasons"] == [
        "missing_case:procedure_missing_guide"
    ]


def test_acceptance_matrix_contains_the_original_model_independent_reference_cases():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))

    assert matrix["schema_version"] == "kahle.harness-acceptance-matrix.v1"
    assert matrix["expected_models"] == [
        "KAHLE-Vinci",
        "KAHLE-Vinci-Thinking",
        "KAHLE-Vinci-Max-Thinking",
    ]
    case_ids = {case["id"] for case in matrix["cases"]}
    assert case_ids == {
        "procedure_without_guide",
        "procedure_with_guide",
        "person_lookup",
        "aliases_and_followup",
        "opening_hours",
        "process_overview",
        "customer_lock_clarification",
        "permissions",
        "model_parity",
        "native_ui",
    }
    assert all(case["required_tool"] == "rag_chat" for case in matrix["cases"])


def test_acceptance_report_accepts_a_deterministic_safe_fallback_delivery():
    reporter = load_reporter()
    run = {
        "case_id": "procedure_without_guide",
        "profile": "employee",
        "metrics": {
            "model_name": "KAHLE-Vinci",
            "tool_called": "rag_chat",
            "evidence_status": "partially_supported",
            "source_count": 1,
            "permission_scope_present": True,
            "final_validation_status": "retry_required",
            "fallback_used": True,
            "delivery_status": "safe_fallback",
            "feedback_link_present": True,
            "latency_ms": 12127,
        },
    }

    report = reporter.build_acceptance_report(
        [run],
        expected_models=("KAHLE-Vinci",),
        profile_authorization={"employee": True},
        required_case_ids=("procedure_without_guide",),
    )

    assert report["summary"]["passed"] == 1
    assert report["coverage"][0]["reasons"] == []


def test_acceptance_report_accepts_a_visible_safe_timeout_fallback():
    reporter = load_reporter()
    run = {
        "case_id": "process_overview",
        "profile": "employee",
        "metrics": {
            "model_name": "KAHLE-Vinci",
            "tool_called": "rag_chat",
            "evidence_status": "supported",
            "source_count": 3,
            "permission_scope_present": True,
            "final_validation_status": "timeout",
            "fallback_used": True,
            "delivery_status": "safe_timeout_fallback",
            "feedback_link_present": True,
            "latency_ms": 90000,
        },
    }

    report = reporter.build_acceptance_report(
        [run],
        expected_models=("KAHLE-Vinci",),
        profile_authorization={"employee": True},
        required_case_ids=("process_overview",),
    )

    assert report["summary"]["passed"] == 1
