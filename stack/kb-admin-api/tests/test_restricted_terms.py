import pytest

from app.restricted_terms import RestrictedTermError, RestrictedTermService
from app.document_lifecycle import Analysis
from test_document_lifecycle import SHA_B, SHA_C, setup, submit


def test_default_terms_match_whole_words_and_require_manager_then_admin(tmp_path):
    governance, lifecycle, kb_id = setup(tmp_path)
    rules = RestrictedTermService(governance, identifier=iter(("rule-1", "rule-2")).__next__)

    assert rules.matches("Diese TPI verweist auf einen Reparaturleitfaden.") == (
        "Reparaturleitfaden", "TPI",
    )
    assert rules.matches("Das Wort atypisch ist kein Treffer.") == ()

    case = submit(lifecycle, kb_id)
    analyzed = lifecycle.record_analysis(
        case_id=case.case_id, normalized_sha256=SHA_B, markdown_sha256=SHA_C,
        analysis=Analysis(restricted_terms=("TPI",)),
    )
    assert analyzed.status == "pending_manager_approval"
    assert analyzed.requested_action == "create"
    assert analyzed.requires_admin is True
    assert [task.case_id for task in lifecycle.tasks_for("manager")] == [case.case_id]
    manager_approved = lifecycle.decide(
        case_id=case.case_id, actor_user_id="manager", decision="approve",
        reason="Sperrwort im fachlichen Kontext geprüft",
    )
    assert manager_approved.status == "pending_admin_approval"
    assert [task.case_id for task in lifecycle.tasks_for("admin")] == [case.case_id]


def test_admin_can_manage_terms_and_changes_are_audited(tmp_path):
    governance, _, _ = setup(tmp_path)
    rules = RestrictedTermService(governance, identifier=iter(("default-1", "default-2", "new-rule")).__next__)

    created = rules.add("admin", "Interne Geheimliste")
    assert created.rule_id == "new-rule"
    assert rules.matches("Das ist eine interne geheimliste für den Test.") == ("Interne Geheimliste",)
    with pytest.raises(RestrictedTermError, match="restricted_term_exists"):
        rules.add("admin", " interne   GEHEIMLISTE ")
    with pytest.raises(RestrictedTermError, match="admin_required"):
        rules.add("employee", "Nicht erlaubt")

    rules.remove("admin", created.rule_id)
    assert rules.matches("Interne Geheimliste") == ()
    events = governance.audit_events("admin")
    assert {event["event_type"] for event in events} >= {
        "restricted_term_added", "restricted_term_removed",
    }
