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
        assert lifecycle.tasks_for("employee") == []
        assert [task.case_id for task in lifecycle.tasks_for("manager")] == [case.case_id]
        assert [task.case_id for task in lifecycle.tasks_for("delegate")] == [case.case_id]
        decided = lifecycle.decide(
            case_id=case.case_id, actor_user_id="delegate", decision="approve",
            reason="Vertretungsweise fachlich geprüft",
        )
        assert decided.status == "ready_to_activate"


def test_absence_saves_selected_delegate_in_one_atomic_workflow():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, _ = setup(Path(directory))
        governance.sync_identity(user_id="delegate", email="delegate@kahle.de", display_name="Vertretung")
        governance.set_absence(
            "admin", "manager", "2026-08-10", "2026-08-20", "Urlaub", "delegate",
        )
        absence = governance.list_absences("admin")[0]
        assert absence["delegate_user_id"] == "delegate"
        delegation = governance.list_delegations("admin")[0]
        assert delegation == {
            "manager_user_id":"manager", "delegate_user_id":"delegate",
            "valid_from":"2026-08-10", "valid_until":"2026-08-20",
        }
        governance.set_absence("admin", "manager", None, None, "Entfernt")
        assert governance.list_absences("admin") == []
        assert governance.list_delegations("admin") == []


def test_cross_knowledgebase_similarity_is_reviewed_by_manager_not_admin():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, kb_id = setup(Path(directory))
        case = submit(lifecycle, kb_id)
        lifecycle.record_analysis(
            case_id=case.case_id, normalized_sha256=SHA_B, markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(cross_kb_matches=("foreign",)),
        )
        lifecycle.choose_action(case_id=case.case_id, actor_user_id="employee", action="create")
        assert lifecycle.tasks_for("admin") == []
        assert [task.case_id for task in lifecycle.tasks_for("manager")] == [case.case_id]
