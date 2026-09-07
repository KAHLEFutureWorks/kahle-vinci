from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import pytest


ROOT = Path(__file__).resolve().parents[1]
REPORTER = ROOT.parent / "scripts" / "openwebui" / "kahle-harness-acceptance.py"
MATRIX = ROOT.parent / "scripts" / "openwebui" / "kahle-harness-acceptance-matrix.json"


def load_reporter():
    spec = importlib.util.spec_from_file_location("kahle_harness_acceptance", REPORTER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def shadow_run(status="accepted", delivery="observed"):
    return {
        "case_id": "trusted_case", "profile": "employee",
        "metrics": {
            "model_id": "KAHLE-Vinci", "intent_kind": "employee_directory",
            "actual_tools": ["personio_directory"], "source_kinds": ["personio_directory"],
            "evidence_status": "supported", "source_count": 1,
            "permission_scope_present": True, "validation_mode": "shadow",
            "delivery_status": delivery, "final_validation_status": status,
            "assertions": {"forbidden_fields_absent": True},
        },
    }


def outcome_matrix(required=("rag_chat",), allowed=("rag_chat", "personio_directory"), sources=("rag_chat",)):
    matrix = trusted_matrix()
    matrix["schema_version"] = "kahle.harness-acceptance-matrix.v2"
    matrix["cases"] = [{
        "id": "trusted_case", "required_tools": list(required),
        "allowed_tools": list(allowed), "expected_source_kinds": list(sources),
        "allowed_source_kinds": list(allowed),
        "allowed_evidence_status": ["supported", "unsupported"],
        "forbidden_fields": ["private_email"],
        "required_assertions": ["forbidden_fields_absent"],
    }]
    return matrix


def outcome_run(tools=("rag_chat",), sources=("rag_chat",)):
    run = shadow_run()
    run["metrics"].update(actual_tools=list(tools), validated_source_kinds=list(sources),
                          feedback_link_present=True)
    return run


def outcome_report(run, matrix=None):
    return load_reporter().build_acceptance_report(
        [run], matrix=matrix or outcome_matrix(), profile_authorization={"employee": True},
    )


@pytest.mark.parametrize("tools", [("rag_chat",), ("rag_chat", "personio_directory"),
                                  ("personio_directory", "rag_chat", "rag_chat")])
def test_outcome_report_accepts_required_tools_with_optional_tools_in_any_order(tools):
    report = outcome_report(outcome_run(tools, tools))
    assert report["summary"]["passed"] == 1
    assert report["results"][0]["required_tools"] == ["rag_chat"]


@pytest.mark.parametrize("tools,reason", [
    (("personio_directory",), "required_tool_missing"),
    (("rag_chat", "web_search"), "tool_not_allowed"),
    (("rag_chat", "private-tool@example.invalid"), "tool_not_allowed"),
])
def test_outcome_report_keeps_missing_and_unexpected_execution_visible(tools, reason):
    report = outcome_report(outcome_run(tools))
    assert report["summary"]["failed"] == 1
    assert reason in report["coverage"][0]["reasons"]
    assert "private-tool@example.invalid" not in json.dumps(report)


def test_outcome_report_never_uses_legacy_plans_or_unvalidated_sources():
    run = outcome_run()
    del run["metrics"]["actual_tools"]
    del run["metrics"]["validated_source_kinds"]
    run["metrics"].update(tool_called="rag_chat", required_tools=["rag_chat"], source_kinds=["rag_chat"])
    reasons = outcome_report(run)["coverage"][0]["reasons"]
    assert "actual_tools_missing" in reasons
    assert "validated_sources_missing" in reasons


def test_outcome_report_requires_validated_source_even_when_tool_ran():
    report = outcome_report(outcome_run(sources=()))
    assert "expected_source_kinds_mismatch" in report["coverage"][0]["reasons"]


def test_outcome_report_rejects_source_without_executed_tool():
    report = outcome_report(outcome_run(sources=("rag_chat", "personio_directory")))
    assert "source_without_tool" in report["coverage"][0]["reasons"]


def test_outcome_report_general_text_needs_neither_tools_nor_observation():
    run = outcome_run((), ())
    run["metrics"].update(evidence_status="unsupported", source_count=0,
                          validation_mode="", delivery_status="accepted",
                          final_validation_status="not_run", feedback_link_present=False)
    report = outcome_report(run, outcome_matrix((), (), ()))
    assert report["summary"]["passed"] == 1


def test_outcome_report_internal_answer_cannot_downgrade_to_legacy_validation():
    run = outcome_run()
    run["metrics"].update(validation_mode="", delivery_status="safe_fallback")
    assert "observation_required" in outcome_report(run)["coverage"][0]["reasons"]


def test_outcome_fault_injection_is_separate_but_never_hidden_if_reported():
    matrix = outcome_matrix()
    fault = {**matrix["cases"][0], "id": "fault_case", "evaluation_group": "fault_injection"}
    matrix["cases"].append(fault)
    assert outcome_report(outcome_run(), matrix)["summary"]["passed"] == 1
    fault_run = outcome_run()
    fault_run["case_id"] = "fault_case"
    fault_run["metrics"]["final_validation_status"] = "retry_required"
    report = load_reporter().build_acceptance_report(
        [outcome_run(), fault_run], matrix=matrix, profile_authorization={"employee": True})
    assert report["summary"]["failed"] == 1
    assert report["observations"][0]["flagged"] == 1


def test_outcome_supported_cannot_use_a_raw_source_count_as_validated_evidence():
    report = outcome_report(outcome_run(sources=()), outcome_matrix(sources=()))
    assert "supported_answer_without_validated_source" in report["coverage"][0]["reasons"]


@pytest.mark.parametrize("tools", [("rag_chat",), ("personio_directory",)])
def test_outcome_explicit_mixed_question_requires_each_tool(tools):
    report = outcome_report(outcome_run(tools, tools),
        outcome_matrix(("personio_directory", "rag_chat"),
                       ("personio_directory", "rag_chat"),
                       ("personio_directory", "rag_chat")))
    assert "required_tool_missing" in report["coverage"][0]["reasons"]


def test_outcome_pure_person_case_rejects_extra_rag():
    report = outcome_report(outcome_run(("personio_directory", "rag_chat")),
        outcome_matrix(("personio_directory",), ("personio_directory",), ("personio_directory",)))
    assert "tool_not_allowed" in report["coverage"][0]["reasons"]


def test_outcome_unknown_sources_are_reported_without_disclosing_raw_labels():
    report = outcome_report(outcome_run(sources=("rag_chat", "private-source@example.invalid")))
    assert "source_kind_not_allowed" in report["coverage"][0]["reasons"]
    assert report["results"][0]["validated_source_kinds"] == ["rag_chat", "unknown_source"]
    assert "private-source@example.invalid" not in json.dumps(report)


def test_outcome_assertions_cannot_be_passed_outside_the_normalized_metrics():
    run = outcome_run()
    run["assertions"] = run["metrics"].pop("assertions")
    report = outcome_report(run)
    assert "assertion_failed:forbidden_fields_absent" in report["coverage"][0]["reasons"]
    assert report["results"][0]["assertions"] == {"forbidden_fields_absent": False}


@pytest.mark.parametrize("field,value", [
    ("required_tools", ["web_search"]), ("allowed_tools", []),
    ("expected_source_kinds", ["personio_directory"]),
])
def test_outcome_matrix_rejects_impossible_source_and_tool_contracts(field, value):
    matrix = outcome_matrix(allowed=("rag_chat",))
    matrix["cases"][0][field] = value
    reporter = load_reporter()
    with pytest.raises(reporter.MatrixContractError):
        reporter.build_acceptance_report([], matrix=matrix)


@pytest.mark.parametrize("status, passed", [
    ("accepted", True), ("retry_required", False),
    ("observation_error", False), ("not_run", False),
])
def test_shadow_report_separates_delivery_from_observed_quality(status, passed):
    reporter = load_reporter()
    report = reporter.build_acceptance_report(
        [shadow_run(status)], matrix=trusted_matrix(), profile_authorization={"employee": True},
    )
    assert (report["summary"]["passed"] == 1) is passed
    result = report["results"][0]
    assert result["validation_mode"] == "shadow"
    assert result["delivery_status"] == "observed"
    assert result["validation_status"] == status


def test_shadow_report_does_not_treat_a_replaced_answer_as_unmodified_delivery():
    reporter = load_reporter()
    report = reporter.build_acceptance_report(
        [shadow_run("accepted", "safe_fallback")], matrix=trusted_matrix(),
        profile_authorization={"employee": True},
    )
    assert report["summary"]["failed"] == 1


def test_shadow_report_counts_findings_and_missing_observations_separately():
    reporter = load_reporter()
    runs = [shadow_run(status) for status in ("accepted", "retry_required", "observation_error", "not_run")]
    runs[1]["answer"] = "private@example.invalid"
    report = reporter.build_acceptance_report(runs, matrix=trusted_matrix(), profile_authorization={"employee": True})
    assert report["observations"] == [{
        "model_id": "KAHLE-Vinci", "profile": "employee", "sample_size": 4,
        "checked": 2, "flagged": 1, "observation_errors": 1, "not_observed": 1,
        "flagged_rate": 0.5,
    }]
    assert "private@example.invalid" not in json.dumps(report)


def trusted_matrix(*, models=("KAHLE-Vinci",), profiles=("employee",), cases=None):
    return {
        "schema_version": "kahle.harness-acceptance-matrix.v1",
        "expected_models": list(models),
        "profiles": list(profiles),
        "cases": list(
            cases
            or [
                {
                    "id": "trusted_case",
                    "expected_tools": ["personio_directory"],
                    "expected_intent": "employee_directory",
                    "allowed_evidence_status": ["supported", "unsupported"],
                    "allowed_source_kinds": ["personio_directory"],
                    "forbidden_fields": ["private_email"],
                    "required_assertions": ["forbidden_fields_absent"],
                }
            ]
        ),
    }


def matrix_from_contracts(contracts, *, models=("KAHLE-Vinci",), profiles=("employee",)):
    return trusted_matrix(
        models=models,
        profiles=profiles,
        cases=[{"id": case_id, **contract} for case_id, contract in contracts.items()],
    )


def test_acceptance_report_distinguishes_passed_unavailable_and_not_authorized():
    reporter = load_reporter()
    runs = [
        {
            "case_id": "person_lookup",
            "profile": "employee",
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
                "assertions": {"forbidden_fields_absent": True},
            },
        },
        {
            "case_id": "person_lookup",
            "profile": "employee",
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
                "assertions": {"forbidden_fields_absent": True},
            },
        },
    ]

    report = reporter.build_acceptance_report(
        runs,
        matrix=trusted_matrix(
            models=(
                "KAHLE-Vinci",
                "KAHLE-Vinci-Thinking",
                "KAHLE-Vinci-Max-Thinking",
            ),
            profiles=("employee", "manager"),
            cases=[
                {
                    "id": "person_lookup",
                    "expected_tools": ["rag_chat"],
                    "expected_intent": "employee_directory",
                    "allowed_evidence_status": ["supported"],
                    "forbidden_fields": ["private_email"],
                }
            ],
        ),
        profile_authorization={"employee": True, "manager": False},
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
            "assertions": {"forbidden_fields_absent": True},
        },
    }

    report = reporter.build_acceptance_report(
        [run],
        matrix=trusted_matrix(
            cases=[
                {
                    "id": "person_lookup",
                    "expected_tools": ["rag_chat"],
                    "expected_intent": "employee_directory",
                    "allowed_evidence_status": ["supported"],
                    "forbidden_fields": ["private_email"],
                },
                {
                    "id": "procedure_missing_guide",
                    "expected_tools": ["rag_chat"],
                    "expected_intent": "internal_knowledge",
                    "allowed_evidence_status": ["unsupported"],
                    "forbidden_fields": ["private_email"],
                },
            ]
        ),
        profile_authorization={"employee": True},
    )

    assert report["summary"]["failed"] == 1
    assert report["coverage"][0]["status"] == "failed"
    assert report["coverage"][0]["reasons"] == [
        "missing_case:procedure_missing_guide"
    ]


def test_acceptance_matrix_contains_the_original_model_independent_reference_cases():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))

    assert matrix["schema_version"] == "kahle.harness-acceptance-matrix.v2"
    assert matrix["expected_models"] == [
        "KAHLE-Vinci",
        "KAHLE-Vinci-Thinking",
        "KAHLE-Vinci-Max-Thinking",
    ]
    case_ids = {case["id"] for case in matrix["cases"]}
    assert {
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
    }.issubset(case_ids)
    assert {
        "directory_filtering",
        "onboarding_hidden",
        "onboarding_explicit",
        "coworker_team",
        "coworker_position_office",
        "coworker_department_office",
        "pure_rag_process",
        "mixed_person_project",
        "empty_personio_no_fallback",
        "pending_directory_denied",
        "stale_directory_warning",
        "onboarding_general",
        "directory_role_location",
        "directory_role_brand",
        "supervisor_no_evidence",
        "process_responsibility_invoice",
        "process_responsibility_complaint",
    }.issubset(case_ids)
    for case in matrix["cases"]:
        assert case["required_tools"] in (
            ["personio_directory"],
            ["rag_chat"],
            ["personio_directory", "rag_chat"],
            [],
        )
        assert set(case["required_tools"]).issubset(case["allowed_tools"])
        assert case["allowed_evidence_status"]
        assert case["forbidden_fields"]


def test_contact_matrix_covers_positive_negative_context_and_unmodified_delivery():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in matrix["cases"]}
    assert {
        "functional_contact_email", "functional_contact_phone", "functional_contact_page",
        "functional_contact_prose", "functional_contact_missing_scope",
        "functional_contact_ambiguous_scope", "functional_contact_conflict",
        "functional_contact_denied", "functional_contact_old_version",
        "functional_contact_wrong_assignment", "functional_contact_hint",
        "functional_contact_shadow_fault", "explicit_mailbox_and_current_staff",
        "ambiguous_area_contact", "general_text_no_tools", "compact_noun_query",
        "supervisor_explicit_name_change", "supervisor_referential_followup",
    }.issubset(cases)
    assert cases["explicit_mailbox_and_current_staff"]["required_tools"] == ["personio_directory", "rag_chat"]
    assert cases["ambiguous_area_contact"]["required_tools"] == ["rag_chat"]
    assert set(cases["ambiguous_area_contact"]["allowed_tools"]) == {"rag_chat", "personio_directory"}
    assert cases["functional_contact_shadow_fault"]["evaluation_group"] == "fault_injection"
    assert cases["general_text_no_tools"]["allowed_tools"] == []
    # The real reporter validates the complete versioned contract, not just IDs.
    report = load_reporter().build_acceptance_report([], matrix=matrix)
    assert report["summary"]["passed"] == 0


def test_acceptance_report_rejects_rag_for_a_pure_directory_case():
    reporter = load_reporter()
    contracts = {
        "person_lookup": {
            "expected_tools": ["personio_directory"],
            "expected_intent": "employee_directory",
            "allowed_evidence_status": ["supported"],
            "expected_source_kinds": ["personio_directory"],
            "forbidden_fields": ["private_email", "salary"],
            "required_assertions": ["forbidden_fields_absent"],
        }
    }
    run = {
        "case_id": "person_lookup",
        "profile": "employee",
        "metrics": {
            "model_id": "KAHLE-Vinci",
            "intent_kind": "employee_directory",
            "actual_tools": ["personio_directory", "rag_chat"],
            "evidence_status": "supported",
            "source_kinds": ["personio_directory", "rag_chat"],
            "source_count": 2,
            "permission_scope_present": True,
            "final_validation_status": "accepted",
            "delivery_status": "accepted",
            "feedback_link_present": True,
            "latency_ms": 1200,
            "assertions": {"forbidden_fields_absent": True},
        },
    }

    report = reporter.build_acceptance_report(
        [run],
        matrix=matrix_from_contracts(contracts),
        profile_authorization={"employee": True},
    )

    assert report["summary"]["failed"] == 1
    assert "expected_tools_mismatch" in report["coverage"][0]["reasons"]


def test_acceptance_report_rejects_mixed_case_missing_either_tool():
    reporter = load_reporter()
    contracts = {
        "mixed_person_project": {
            "expected_tools": ["personio_directory", "rag_chat"],
            "expected_intent": "employee_directory",
            "allowed_evidence_status": ["supported", "partially_supported"],
            "expected_source_kinds": ["personio_directory", "rag_chat"],
            "forbidden_fields": ["private_phone", "salary"],
            "required_assertions": ["forbidden_fields_absent"],
        }
    }
    runs = []
    for tools in (["personio_directory"], ["rag_chat"]):
        runs.append(
            {
                "case_id": "mixed_person_project",
                "profile": "employee",
                "metrics": {
                    "model_id": "KAHLE-Vinci",
                    "intent_kind": "employee_directory",
                    "actual_tools": tools,
                    "evidence_status": "partially_supported",
                    "source_kinds": tools,
                    "source_count": 1,
                    "permission_scope_present": True,
                    "final_validation_status": "accepted",
                    "delivery_status": "accepted",
                    "feedback_link_present": True,
                    "latency_ms": 1100,
                    "assertions": {"forbidden_fields_absent": True},
                },
            }
        )

    report = reporter.build_acceptance_report(
        runs,
        matrix=matrix_from_contracts(contracts),
        profile_authorization={"employee": True},
    )

    assert report["summary"]["failed"] == 1
    assert "expected_tools_mismatch" in report["coverage"][0]["reasons"]


def test_acceptance_report_persists_only_privacy_safe_case_results():
    reporter = load_reporter()
    contracts = {
        "onboarding_explicit": {
            "expected_tools": ["personio_directory"],
            "expected_intent": "employee_directory",
            "allowed_evidence_status": ["supported"],
            "expected_source_kinds": ["personio_directory"],
            "forbidden_fields": ["business_email", "phone", "personio_id"],
            "required_assertions": [
                "forbidden_fields_absent",
                "onboarding_fields_reduced",
            ],
        }
    }
    sensitive_markers = {
        "question": "PII_QUESTION_MARKER",
        "answer": "PII_ANSWER_MARKER",
        "personio_id": "PII_PERSONIO_ID_MARKER",
        "contact_value": "pii-marker@example.invalid",
        "phone": "+49 555 123456",
        "raw_evidence": {"display_name": "PII_NAME_MARKER"},
    }
    run = {
        "case_id": "onboarding_explicit",
        "profile": "employee",
        **sensitive_markers,
        "metrics": {
            "model_id": "KAHLE-Vinci",
            "intent_kind": "employee_directory",
            "actual_tools": ["personio_directory"],
            "evidence_status": "supported",
            "source_kinds": ["personio_directory"],
            "source_count": 1,
            "permission_scope_present": True,
            "final_validation_status": "accepted",
            "delivery_status": "accepted",
            "feedback_link_present": False,
            "latency_ms": 950,
            "assertions": {
                "forbidden_fields_absent": True,
                "onboarding_fields_reduced": True,
                "PII_ASSERTION_KEY_MARKER": True,
            },
            **sensitive_markers,
        },
    }

    report = reporter.build_acceptance_report(
        [run],
        matrix=matrix_from_contracts(contracts),
        profile_authorization={"employee": True},
    )

    assert report["summary"]["passed"] == 1
    assert set(report["results"][0]) == {
        "case_id",
        "model_id",
        "expected_tools",
        "actual_tools",
        "intent",
        "evidence_status",
        "source_kinds",
        "validation_status",
        "latency_ms",
        "assertions",
    }
    assert report["results"][0]["assertions"] == {
        "forbidden_fields_absent": True,
        "onboarding_fields_reduced": True,
    }
    serialized = json.dumps(report, ensure_ascii=False)
    for forbidden in (
        "PII_NAME_MARKER",
        "pii-marker@example.invalid",
        "PII_PERSONIO_ID_MARKER",
        "PII_ASSERTION_KEY_MARKER",
        "PII_QUESTION_MARKER",
        "PII_ANSWER_MARKER",
        "+49 555 123456",
        "raw_evidence",
        "question",
        "answer",
        "contact_value",
    ):
        assert forbidden not in serialized


def test_versioned_matrix_is_the_only_coverage_source_and_empty_input_fails_closed():
    reporter = load_reporter()
    matrix = trusted_matrix(
        models=("KAHLE-Vinci", "KAHLE-Vinci-Thinking"),
        profiles=("employee", "manager"),
    )

    empty_report = reporter.build_report_from_payload({}, matrix=matrix)
    manipulated_report = reporter.build_report_from_payload(
        {
            "expected_models": [],
            "profile_authorization": {"employee": True, "manager": True},
            "required_case_ids": [],
            "runs": [],
        },
        matrix=matrix,
    )

    for report in (empty_report, manipulated_report):
        assert len(report["coverage"]) == 4
        assert {
            entry["model_name"] for entry in report["coverage"]
        } == {"KAHLE-Vinci", "KAHLE-Vinci-Thinking"}
        assert {entry["profile"] for entry in report["coverage"]} == {
            "employee",
            "manager",
        }
        assert report["summary"]["passed"] == 0
        assert reporter.acceptance_exit_code(report) == 1


def test_external_ids_cannot_extend_coverage_or_leak_into_results_and_reasons():
    reporter = load_reporter()
    matrix = trusted_matrix()
    payload = {
        "expected_models": ["pii-model@example.invalid"],
        "required_case_ids": ["PII Full Name 4711"],
        "profile_authorization": {
            "employee": True,
            "PII_PROFILE_MARKER": True,
        },
        "runs": [
            {
                "case_id": "PII_CASE_ID_MARKER",
                "profile": "employee",
                "metrics": {
                    "model_id": "KAHLE-Vinci",
                    "model_name": "pii-model-name@example.invalid",
                    "intent_kind": "employee_directory",
                    "tool_called": "rag_chat",
                    "evidence_status": "unsupported",
                    "source_count": 0,
                    "permission_scope_present": True,
                    "final_validation_status": "accepted",
                    "delivery_status": "accepted",
                    "feedback_link_present": True,
                    "latency_ms": 10,
                },
            },
            {
                "case_id": "trusted_case",
                "profile": "PII_PROFILE_MARKER",
                "metrics": {
                    "model_id": "pii-run-model@example.invalid",
                    "intent_kind": "PII_INTENT_MARKER",
                    "evidence_status": "PII_EVIDENCE_MARKER",
                    "delivery_status": "PII_VALIDATION_MARKER",
                },
            },
        ],
    }

    report = reporter.build_report_from_payload(payload, matrix=matrix)

    assert report["coverage"] == [
        {
            "model_name": "KAHLE-Vinci",
            "profile": "employee",
            "status": "failed",
            "run_count": 1,
            "reasons": ["missing_case:trusted_case"],
        }
    ]
    assert report["results"][0]["case_id"] == "unknown_case"
    assert report["results"][0]["model_id"] == "KAHLE-Vinci"
    assert report["results"][1]["model_id"] == "unknown_model"
    serialized = json.dumps(report)
    for marker in (
        "pii-model@example.invalid",
        "PII Full Name 4711",
        "PII_PROFILE_MARKER",
        "PII_CASE_ID_MARKER",
        "pii-model-name@example.invalid",
        "pii-run-model@example.invalid",
        "PII_INTENT_MARKER",
        "PII_EVIDENCE_MARKER",
        "PII_VALIDATION_MARKER",
    ):
        assert marker not in serialized
    assert reporter.acceptance_exit_code(report) == 1


def test_acceptance_report_does_not_persist_untrusted_identifier_fields():
    reporter = load_reporter()
    run = {
        "case_id": "PII_CASE_ID_MARKER",
        "profile": "PII_PROFILE_MARKER",
        "metrics": {
            "model_id": "pii-model-marker@example.invalid",
            "intent_kind": "PII_INTENT_MARKER",
            "actual_tools": [],
            "evidence_status": "PII_EVIDENCE_MARKER",
            "permission_scope_present": True,
            "final_validation_status": "accepted",
            "delivery_status": "PII_VALIDATION_MARKER",
            "latency_ms": 10,
        },
    }

    report = reporter.build_acceptance_report(
        [run],
        matrix=matrix_from_contracts(
            {
                "known_case": {
                    "expected_tools": ["personio_directory"],
                    "expected_intent": "employee_directory",
                    "allowed_evidence_status": ["supported", "unsupported"],
                    "forbidden_fields": ["private_email"],
                }
            }
        ),
        profile_authorization={"employee": True},
    )

    assert report["results"][0]["case_id"] == "unknown_case"
    assert report["results"][0]["model_id"] == "unknown_model"
    assert report["results"][0]["intent"] == "unknown_intent"
    assert report["results"][0]["evidence_status"] == "unknown"
    assert report["results"][0]["validation_status"] == "unknown"
    serialized = json.dumps(report)
    assert "PII_CASE_ID_MARKER" not in serialized
    assert "PII_PROFILE_MARKER" not in serialized
    assert "pii-model-marker@example.invalid" not in serialized
    assert "PII_INTENT_MARKER" not in serialized
    assert "PII_EVIDENCE_MARKER" not in serialized
    assert "PII_VALIDATION_MARKER" not in serialized


def test_acceptance_report_accepts_a_deterministic_safe_fallback_delivery():
    reporter = load_reporter()
    run = {
        "case_id": "procedure_without_guide",
        "profile": "employee",
        "metrics": {
            "model_name": "KAHLE-Vinci",
            "intent_kind": "internal_knowledge",
            "tool_called": "rag_chat",
            "evidence_status": "partially_supported",
            "source_count": 1,
            "permission_scope_present": True,
            "final_validation_status": "retry_required",
            "fallback_used": True,
            "delivery_status": "safe_fallback",
            "feedback_link_present": True,
            "latency_ms": 12127,
            "assertions": {"forbidden_fields_absent": True},
        },
    }

    report = reporter.build_acceptance_report(
        [run],
        matrix=trusted_matrix(
            cases=[
                {
                    "id": "procedure_without_guide",
                    "expected_tools": ["rag_chat"],
                    "expected_intent": "internal_knowledge",
                    "allowed_evidence_status": ["partially_supported"],
                    "forbidden_fields": ["private_email"],
                }
            ]
        ),
        profile_authorization={"employee": True},
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
            "intent_kind": "internal_knowledge",
            "tool_called": "rag_chat",
            "evidence_status": "supported",
            "source_count": 3,
            "permission_scope_present": True,
            "final_validation_status": "timeout",
            "fallback_used": True,
            "delivery_status": "safe_timeout_fallback",
            "feedback_link_present": True,
            "latency_ms": 90000,
            "assertions": {"forbidden_fields_absent": True},
        },
    }

    report = reporter.build_acceptance_report(
        [run],
        matrix=trusted_matrix(
            cases=[
                {
                    "id": "process_overview",
                    "expected_tools": ["rag_chat"],
                    "expected_intent": "internal_knowledge",
                    "allowed_evidence_status": ["supported"],
                    "forbidden_fields": ["private_email"],
                }
            ]
        ),
        profile_authorization={"employee": True},
    )

    assert report["summary"]["passed"] == 1


def test_acceptance_report_enforces_case_evidence_intent_and_assertions():
    reporter = load_reporter()
    run = {
        "case_id": "procedure_without_guide",
        "profile": "employee",
        "assertions": {
            "no_unsubstantiated_steps": False,
            "missing_information_disclosed": True,
        },
        "metrics": {
            "model_name": "KAHLE-Vinci",
            "intent_kind": "employee_directory",
            "tool_called": "rag_chat",
            "evidence_status": "supported",
            "source_count": 1,
            "permission_scope_present": True,
            "final_validation_status": "accepted",
            "feedback_link_present": True,
        },
    }
    contracts = {
        "procedure_without_guide": {
            "required_tool": "rag_chat",
            "expected_intent": "internal_knowledge",
            "allowed_evidence_status": ["partially_supported", "unsupported"],
            "required_assertions": [
                "no_unsubstantiated_steps",
                "missing_information_disclosed",
            ],
        }
    }

    report = reporter.build_acceptance_report(
        [run],
        expected_models=("KAHLE-Vinci",),
        profile_authorization={"employee": True},
        required_case_ids=("procedure_without_guide",),
        case_contracts=contracts,
    )

    assert report["summary"]["failed"] == 1
    assert report["coverage"][0]["reasons"] == [
        "case:procedure_without_guide:assertion_failed:no_unsubstantiated_steps",
        "case:procedure_without_guide:evidence_status_not_allowed:supported",
        "case:procedure_without_guide:unexpected_intent:employee_directory",
    ]


def test_acceptance_report_requires_explicit_case_assertion_results():
    reporter = load_reporter()
    run = {
        "case_id": "native_ui",
        "profile": "employee",
        "metrics": {
            "model_name": "KAHLE-Vinci",
            "tool_called": "rag_chat",
            "evidence_status": "supported",
            "source_count": 1,
            "permission_scope_present": True,
            "final_validation_status": "accepted",
            "feedback_link_present": True,
        },
    }

    report = reporter.build_acceptance_report(
        [run],
        expected_models=("KAHLE-Vinci",),
        profile_authorization={"employee": True},
        required_case_ids=("native_ui",),
        case_contracts={
            "native_ui": {
                "required_tool": "rag_chat",
                "allowed_evidence_status": ["supported"],
                "required_assertions": ["answer_stable"],
            }
        },
    )

    assert report["coverage"][0]["reasons"] == [
        "case:native_ui:assertion_missing:answer_stable"
    ]


def test_acceptance_report_compares_model_parity_core_status_and_sources():
    reporter = load_reporter()

    def parity_run(model_name, core, sources):
        return {
            "case_id": "model_parity",
            "profile": "employee",
            "assertions": {"business_data_only": True},
            "comparison": {"factual_core": core, "source_ids": sources},
            "metrics": {
                "model_name": model_name,
                "tool_called": "rag_chat",
                "evidence_status": "supported",
                "source_count": len(sources),
                "permission_scope_present": True,
                "final_validation_status": "accepted",
                "feedback_link_present": True,
            },
        }

    report = reporter.build_acceptance_report(
        [
            parity_run("KAHLE-Vinci", "thomas-keller-management", ["policy"]),
            parity_run("KAHLE-Vinci-Thinking", "different-core", ["other"]),
        ],
        expected_models=("KAHLE-Vinci", "KAHLE-Vinci-Thinking"),
        profile_authorization={"employee": True},
        required_case_ids=("model_parity",),
        case_contracts={
            "model_parity": {
                "required_tool": "rag_chat",
                "allowed_evidence_status": ["supported", "unsupported"],
                "required_assertions": ["business_data_only"],
                "compare_across_models": [
                    "evidence_status", "factual_core", "source_ids",
                ],
            }
        },
    )

    assert report["summary"]["failed"] == 2
    for entry in report["coverage"]:
        assert entry["reasons"] == [
            "case:model_parity:model_parity_mismatch:factual_core,source_ids"
        ]
