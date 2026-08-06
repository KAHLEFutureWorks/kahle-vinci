import tempfile
from pathlib import Path

from test_document_lifecycle import SHA_B, SHA_C, lifecycle_module, setup, submit


def test_role_task_queues_and_manager_delegate_decision():
    with tempfile.TemporaryDirectory() as directory:
        governance, lifecycle, kb_id = setup(Path(directory))
        governance.sync_identity(user_id="delegate", email="delegate@kahle.de", display_name="Vertretung")
        governance.set_role("portal", "delegate", "manager")
        governance.assign_delegate(
            "admin", "manager", "delegate", valid_from="2026-08-01", valid_until="2026-08-31"
        )
        governance.set_absence("admin", "manager", "2026-08-01", "2026-08-31", "Urlaub")
        case = submit(lifecycle, kb_id)
        lifecycle.record_analysis(
            case_id=case.case_id, normalized_sha256=SHA_B, markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(),
        )
        assert [task.case_id for task in lifecycle.tasks_for("employee")] == [case.case_id]
        lifecycle.choose_action(case_id=case.case_id, actor_user_id="employee", action="create")
        assert [task.case_id for task in lifecycle.tasks_for("manager")] == [case.case_id]
        assert [task.case_id for task in lifecycle.tasks_for("delegate")] == [case.case_id]
        decided = lifecycle.decide(
            case_id=case.case_id, actor_user_id="delegate", decision="approve",
            reason="Vertretungsweise fachlich geprüft",
        )
        assert decided.status == "pending_admin_approval"


def test_admin_queue_only_receives_escalated_case():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, kb_id = setup(Path(directory))
        case = submit(lifecycle, kb_id)
        lifecycle.record_analysis(
            case_id=case.case_id, normalized_sha256=SHA_B, markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(cross_kb_matches=("foreign",)),
        )
        lifecycle.choose_action(case_id=case.case_id, actor_user_id="employee", action="create")
        assert [task.case_id for task in lifecycle.tasks_for("admin")] == [case.case_id]
