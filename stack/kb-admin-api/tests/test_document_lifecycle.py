from __future__ import annotations

import importlib.util
import sys
import tempfile
from datetime import date
from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))


def load(name: str):
    path = APP / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


governance_module = load("portal_governance")
lifecycle_module = load("document_lifecycle")
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def setup(root: Path):
    ids = iter(f"id-{index}" for index in range(1, 200))
    store = governance_module.SQLiteGovernanceStore(root / "portal.sqlite3")
    governance = governance_module.PortalGovernance(
        store,
        now=lambda: "2026-08-06T10:00:00+00:00",
        identifier=lambda: next(ids),
    )
    governance.sync_identity(
        user_id="portal", email="portal@kahle.de", display_name="Portal", bootstrap_portal_admin=True
    )
    governance.sync_identity(user_id="admin", email="admin@kahle.de", display_name="Admin")
    governance.sync_identity(user_id="manager", email="manager@kahle.de", display_name="Leitung")
    governance.sync_identity(user_id="employee", email="employee@kahle.de", display_name="Mitarbeiter")
    governance.set_role("portal", "admin", "admin")
    governance.set_role("portal", "manager", "manager")
    governance.assign_manager("admin", "employee", "manager")
    kb = governance.request_knowledgebase_change(
        "portal", "create", payload={"slug": "service", "label": "Service"}
    )
    governance.grant_access(
        "admin", "employee", kb.knowledgebase_id, can_read=True, can_upload=True
    )
    lifecycle = lifecycle_module.DocumentLifecycle(
        store,
        governance,
        today=lambda: date(2026, 8, 6),
        now=lambda: "2026-08-06T10:00:00+00:00",
        identifier=lambda: next(ids),
        holidays=set(),
    )
    return governance, lifecycle, kb.knowledgebase_id


def submit(lifecycle, kb_id, sha=SHA_A, document_id=None):
    return lifecycle.submit(
        uploaded_by_user_id="employee",
        owner_user_id="employee",
        target_knowledgebase_id=kb_id,
        title="Arbeitsanweisung",
        original_filename="arbeitsanweisung.docx",
        original_file_id="file-1",
        original_sha256=sha,
        valid_workdays=60,
        confidentiality="restricted",
        document_id=document_id,
    )


def test_standard_manager_flow_activates_with_60_workday_expiry():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, kb_id = setup(Path(directory))
        case = submit(lifecycle, kb_id)
        case = lifecycle.record_analysis(
            case_id=case.case_id,
            normalized_sha256=SHA_B,
            markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(),
        )
        assert case.status == "pending_employee_decision"
        case = lifecycle.choose_action(case_id=case.case_id, actor_user_id="employee", action="create")
        assert case.status == "pending_manager_approval"
        case = lifecycle.decide(
            case_id=case.case_id,
            actor_user_id="manager",
            decision="approve",
            reason="Fachlich geprüft",
        )
        assert case.status == "pending_admin_approval"
        case = lifecycle.decide(
            case_id=case.case_id, actor_user_id="admin", decision="approve", reason="Portalfreigabe",
        )
        assert case.status == "ready_to_activate"
        case = lifecycle.activate(case_id=case.case_id)
        version = lifecycle.version_record(case.version_id)
        assert case.status == "active"
        assert version["valid_from"] == "2026-08-06"
        assert version["valid_until"] == "2026-10-29"


def test_cross_kb_or_contradiction_requires_admin_and_cannot_be_manager_approved():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, kb_id = setup(Path(directory))
        case = submit(lifecycle, kb_id)
        case = lifecycle.record_analysis(
            case_id=case.case_id,
            normalized_sha256=SHA_B,
            markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(
                cross_kb_matches=("other-document",),
                contradiction_document_ids=("policy-document",),
            ),
        )
        assert case.requires_admin is True
        case = lifecycle.choose_action(case_id=case.case_id, actor_user_id="employee", action="create")
        assert case.status == "pending_admin_approval"
        try:
            lifecycle.decide(
                case_id=case.case_id,
                actor_user_id="manager",
                decision="approve",
                reason="Soll passen",
            )
            raise AssertionError("manager must not resolve cross-kb conflicts")
        except lifecycle_module.LifecycleError as exc:
            assert str(exc) == "admin_required"
        approved = lifecycle.decide(
            case_id=case.case_id,
            actor_user_id="admin",
            decision="approve",
            reason="Geltungsbereich geprüft",
        )
        assert approved.status == "ready_to_activate"


def test_exact_duplicate_is_blocked_and_only_publish_or_discard_is_allowed():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, kb_id = setup(Path(directory))
        case = submit(lifecycle, kb_id)
        case = lifecycle.record_analysis(
            case_id=case.case_id,
            normalized_sha256=SHA_B,
            markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(exact_duplicate_document_id="existing-doc"),
        )
        assert case.status == "duplicate_blocked"
        try:
            lifecycle.choose_action(case_id=case.case_id, actor_user_id="employee", action="create")
            raise AssertionError("an exact duplicate must not become a second document")
        except lifecycle_module.LifecycleError as exc:
            assert str(exc) == "exact_duplicate_action_forbidden"
        escalated = lifecycle.choose_action(
            case_id=case.case_id, actor_user_id="employee", action="publish_existing"
        )
        assert escalated.status == "pending_admin_approval"


def test_new_version_atomically_supersedes_previous_active_version():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, kb_id = setup(Path(directory))
        first = submit(lifecycle, kb_id)
        lifecycle.record_analysis(
            case_id=first.case_id,
            normalized_sha256=SHA_B,
            markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(),
        )
        lifecycle.choose_action(case_id=first.case_id, actor_user_id="employee", action="create")
        lifecycle.decide(
            case_id=first.case_id,
            actor_user_id="manager",
            decision="approve",
            reason="Erstfassung",
        )
        lifecycle.decide(case_id=first.case_id, actor_user_id="admin", decision="approve", reason="Portalfreigabe")
        active_first = lifecycle.activate(case_id=first.case_id)

        second = submit(lifecycle, kb_id, sha="d" * 64, document_id=first.document_id)
        lifecycle.record_analysis(
            case_id=second.case_id,
            normalized_sha256="e" * 64,
            markdown_sha256="f" * 64,
            analysis=lifecycle_module.Analysis(same_kb_similarity="very_high"),
        )
        lifecycle.choose_action(case_id=second.case_id, actor_user_id="employee", action="replace")
        lifecycle.decide(
            case_id=second.case_id,
            actor_user_id="manager",
            decision="approve",
            reason="Neue gültige Version",
        )
        lifecycle.decide(
            case_id=second.case_id, actor_user_id="admin", decision="approve", reason="Portalfreigabe"
        )
        active_second = lifecycle.activate(case_id=second.case_id)
        assert lifecycle.version_record(active_first.version_id)["status"] == "superseded"
        assert lifecycle.version_record(active_second.version_id)["status"] == "active"


def test_failed_index_activation_restores_previous_active_version():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, kb_id = setup(Path(directory))
        first = submit(lifecycle, kb_id)
        lifecycle.record_analysis(
            case_id=first.case_id, normalized_sha256=SHA_B, markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(cross_kb_matches=("admin-review",)),
        )
        lifecycle.choose_action(case_id=first.case_id, actor_user_id="employee", action="create")
        lifecycle.decide(case_id=first.case_id, actor_user_id="admin", decision="approve", reason="Freigabe")
        first = lifecycle.activate(case_id=first.case_id)

        second = submit(lifecycle, kb_id, sha="d" * 64, document_id=first.document_id)
        lifecycle.record_analysis(
            case_id=second.case_id, normalized_sha256="e" * 64, markdown_sha256="f" * 64,
            analysis=lifecycle_module.Analysis(cross_kb_matches=("admin-review",)),
        )
        lifecycle.choose_action(case_id=second.case_id, actor_user_id="employee", action="replace")
        lifecycle.decide(case_id=second.case_id, actor_user_id="admin", decision="approve", reason="Freigabe")
        previous = lifecycle.active_version(first.document_id)
        lifecycle.activate(case_id=second.case_id)
        rolled_back = lifecycle.rollback_activation(
            case_id=second.case_id, previous_version_id=previous, reason="index unavailable"
        )

        assert rolled_back.status == "ready_to_activate"
        assert lifecycle.active_version(first.document_id) == first.version_id
        assert lifecycle.version_record(first.version_id)["status"] == "active"
        assert lifecycle.version_record(second.version_id)["status"] == "ready_to_activate"


if __name__ == "__main__":
    test_standard_manager_flow_activates_with_60_workday_expiry()
    test_cross_kb_or_contradiction_requires_admin_and_cannot_be_manager_approved()
    test_exact_duplicate_is_blocked_and_only_publish_or_discard_is_allowed()
    test_new_version_atomically_supersedes_previous_active_version()
    print("document lifecycle tests passed")
