from __future__ import annotations

import importlib.util
import sys
import tempfile
from datetime import date, timedelta
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


def submit(lifecycle, kb_id, sha=SHA_A, document_id=None, title="Arbeitsanweisung"):
    return lifecycle.submit(
        uploaded_by_user_id="employee",
        owner_user_id="employee",
        target_knowledgebase_id=kb_id,
        title=title,
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
        assert case.status == "pending_manager_approval"
        case = lifecycle.decide(
            case_id=case.case_id,
            actor_user_id="manager",
            decision="approve",
            reason="Fachlich geprüft",
        )
        assert case.status == "ready_to_activate"
        case = lifecycle.activate(case_id=case.case_id)
        version = lifecycle.version_record(case.version_id)
        assert case.status == "active"
        assert version["valid_from"] == "2026-08-06"
        assert version["valid_until"] == "2026-10-29"


def test_sanitized_security_review_is_routed_directly_to_admin():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, kb_id = setup(Path(directory))
        case = submit(lifecycle, kb_id)
        case = lifecycle.record_analysis(
            case_id=case.case_id,
            normalized_sha256=SHA_B,
            markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(),
        )
        case = lifecycle.route_sanitized_security_review(
            case_id=case.case_id,
            actor_user_id="employee",
            finding="embedded_executable_content_not_allowed",
        )
        assert case.status == "pending_admin_approval"
        assert case.requires_admin is True
        with lifecycle.store.connect() as db:
            analysis = __import__("json").loads(db.execute(
                "SELECT analysis_json FROM document_cases WHERE case_id=?", (case.case_id,),
            ).fetchone()["analysis_json"])
        assert analysis["sanitized_for_review"] is True


def test_multiple_target_knowledgebases_are_activated_together():
    with tempfile.TemporaryDirectory() as directory:
        governance, lifecycle, first_kb = setup(Path(directory))
        second = governance.request_knowledgebase_change(
            "portal", "create", payload={"slug": "verkauf", "label": "Verkauf"},
        )
        governance.grant_access(
            "admin", "employee", second.knowledgebase_id, can_read=True, can_upload=True,
        )
        case = lifecycle.submit(
            uploaded_by_user_id="employee", owner_user_id="employee",
            target_knowledgebase_id=first_kb,
            target_knowledgebase_ids=(first_kb, second.knowledgebase_id),
            title="Bereichsübergreifende Arbeitsanweisung",
            original_filename="anweisung.pdf", original_file_id="file-multiple",
            original_sha256=SHA_A, valid_workdays=30, confidentiality="internal",
        )
        case = lifecycle.record_analysis(
            case_id=case.case_id, normalized_sha256=SHA_B,
            markdown_sha256=SHA_C, analysis=lifecycle_module.Analysis(),
        )
        case = lifecycle.decide(
            case_id=case.case_id, actor_user_id="manager",
            decision="approve", reason="Fachlich geprüft",
        )
        lifecycle.activate(case_id=case.case_id)

        active = {
            publication["knowledgebase_id"]
            for publication in lifecycle.publications_of(case.document_id)
            if publication["status"] == "active"
        }
        assert active == {first_kb, second.knowledgebase_id}


def test_changing_targets_only_updates_the_selected_case():
    with tempfile.TemporaryDirectory() as directory:
        governance, lifecycle, first_kb = setup(Path(directory))
        second = governance.request_knowledgebase_change(
            "portal", "create", payload={"slug": "verkauf", "label": "Verkauf"},
        )
        first_case = submit(lifecycle, first_kb, sha=SHA_A)
        other_case = submit(lifecycle, first_kb, sha=SHA_B)
        first_case = lifecycle.record_analysis(
            case_id=first_case.case_id, normalized_sha256="d" * 64,
            markdown_sha256="e" * 64, analysis=lifecycle_module.Analysis(),
        )
        lifecycle.record_analysis(
            case_id=other_case.case_id, normalized_sha256="f" * 64,
            markdown_sha256="1" * 64, analysis=lifecycle_module.Analysis(),
        )

        lifecycle.change_target_knowledgebases(
            case_id=first_case.case_id, actor_user_id="manager",
            knowledgebase_ids=(first_kb, second.knowledgebase_id),
        )

        changed = {
            item["knowledgebase_id"] for item in lifecycle.publications_of(first_case.document_id)
            if item["status"] != "inactive"
        }
        untouched = {
            item["knowledgebase_id"] for item in lifecycle.publications_of(other_case.document_id)
            if item["status"] != "inactive"
        }
        assert changed == {first_kb, second.knowledgebase_id}
        assert untouched == {first_kb}


def test_changing_targets_does_not_reorder_open_tasks():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, first_kb = setup(Path(directory))
        clock = {"now": "2026-08-06T10:00:00+00:00"}
        lifecycle = lifecycle_module.DocumentLifecycle(
            governance.store, governance,
            today=lambda: date(2026, 8, 6), now=lambda: clock["now"],
            identifier=lambda: str(__import__("uuid").uuid4()), holidays=set(),
        )
        second_kb = governance.request_knowledgebase_change(
            "portal", "create", payload={"slug": "verkauf", "label": "Verkauf"},
        ).knowledgebase_id

        first_case = submit(lifecycle, first_kb, sha=SHA_A)
        first_case = lifecycle.record_analysis(
            case_id=first_case.case_id, normalized_sha256="2" * 64,
            markdown_sha256="3" * 64, analysis=lifecycle_module.Analysis(),
        )
        clock["now"] = "2026-08-06T11:00:00+00:00"
        second_case = submit(lifecycle, first_kb, sha=SHA_B)
        lifecycle.record_analysis(
            case_id=second_case.case_id, normalized_sha256="4" * 64,
            markdown_sha256="5" * 64, analysis=lifecycle_module.Analysis(),
        )
        before = [task.case_id for task in lifecycle.tasks_for("manager")]
        assert before == [first_case.case_id, second_case.case_id]

        clock["now"] = "2026-08-06T12:00:00+00:00"
        lifecycle.change_target_knowledgebases(
            case_id=first_case.case_id, actor_user_id="manager",
            knowledgebase_ids=(first_kb, second_kb),
        )

        after = [task.case_id for task in lifecycle.tasks_for("manager")]
        assert after == before


def test_clean_area_document_is_ready_for_automatic_activation_when_enabled():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, kb_id = setup(Path(directory))
        lifecycle = lifecycle_module.DocumentLifecycle(
            governance.store,
            governance,
            today=lambda: date(2026, 8, 6),
            now=lambda: "2026-08-06T10:00:00+00:00",
            identifier=lambda: str(__import__("uuid").uuid4()),
            holidays=set(),
            auto_activation_enabled=lambda: True,
        )
        case = submit(lifecycle, kb_id)
        analyzed = lifecycle.record_analysis(
            case_id=case.case_id, normalized_sha256=SHA_B, markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(),
        )
        assert analyzed.status == "ready_to_activate"
        assert analyzed.requested_action == "create"
        assert analyzed.requires_admin is False


def test_clean_general_document_goes_directly_to_manager_without_employee_action():
    with tempfile.TemporaryDirectory() as directory:
        governance, _, _ = setup(Path(directory))
        general = governance.request_knowledgebase_change(
            "portal", "create", payload={"slug":"kahleallgemein","label":"KAHLE-Allgemein"},
        )
        governance.grant_access(
            "admin", "employee", general.knowledgebase_id, can_read=True, can_upload=True,
        )
        lifecycle = lifecycle_module.DocumentLifecycle(
            governance.store, governance, auto_activation_enabled=lambda: True,
        )
        case = submit(lifecycle, general.knowledgebase_id)
        analyzed = lifecycle.record_analysis(
            case_id=case.case_id, normalized_sha256=SHA_B, markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(),
        )
        assert analyzed.status == "pending_manager_approval"
        assert analyzed.requested_action == "create"
        approved = lifecycle.decide(
            case_id=case.case_id, actor_user_id="manager", decision="approve",
            reason="Für KAHLE-Allgemein fachlich geprüft",
        )
        assert approved.status == "ready_to_activate"


def test_portal_admin_can_resolve_critical_own_upload_once_with_written_reason():
    with tempfile.TemporaryDirectory() as directory:
        governance, lifecycle, kb_id = setup(Path(directory))
        governance.grant_access("portal", "portal", kb_id, can_read=True, can_upload=True)
        case = lifecycle.submit(
            uploaded_by_user_id="portal", owner_user_id="portal",
            target_knowledgebase_id=kb_id, title="Kritische Richtlinie",
            original_filename="richtlinie.md", original_file_id="file-portal",
            original_sha256="d"*64, valid_workdays=60, confidentiality="restricted",
        )
        analyzed = lifecycle.record_analysis(
            case_id=case.case_id, normalized_sha256="e"*64, markdown_sha256="f"*64,
            analysis=lifecycle_module.Analysis(restricted_terms=("TPI",)),
        )
        assert analyzed.status == "pending_manager_approval"
        approved = lifecycle.decide(
            case_id=case.case_id, actor_user_id="portal", decision="approve",
            reason="Als Portal-Admin geprüft; TPI ist hier fachlich erforderlich.",
        )
        assert approved.status == "ready_to_activate"


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
        assert case.status == "pending_manager_approval"
        case = lifecycle.decide(
            case_id=case.case_id, actor_user_id="manager", decision="approve",
            reason="Fachlich vorgeprüft",
        )
        assert case.status == "pending_admin_approval"
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
        assert escalated.status == "pending_manager_approval"
        approved = lifecycle.decide(
            case_id=case.case_id, actor_user_id="manager", decision="approve",
            reason="Dublette und Zielbereich geprüft",
        )
        assert approved.status == "pending_admin_approval"


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
        lifecycle.decide(
            case_id=first.case_id,
            actor_user_id="manager",
            decision="approve",
            reason="Erstfassung",
        )
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
        lifecycle.decide(case_id=first.case_id, actor_user_id="manager", decision="approve", reason="Fachprüfung")
        first = lifecycle.activate(case_id=first.case_id)

        second = submit(lifecycle, kb_id, sha="d" * 64, document_id=first.document_id)
        lifecycle.record_analysis(
            case_id=second.case_id, normalized_sha256="e" * 64, markdown_sha256="f" * 64,
            analysis=lifecycle_module.Analysis(cross_kb_matches=("admin-review",)),
        )
        lifecycle.choose_action(case_id=second.case_id, actor_user_id="employee", action="replace")
        lifecycle.decide(case_id=second.case_id, actor_user_id="manager", decision="approve", reason="Fachprüfung")
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


def test_cross_kb_exact_duplicate_publishes_existing_canonical_document_only():
    with tempfile.TemporaryDirectory() as directory:
        governance, lifecycle, first_kb = setup(Path(directory))
        first = submit(lifecycle, first_kb)
        lifecycle.record_analysis(case_id=first.case_id, normalized_sha256=SHA_B,
                                  markdown_sha256=SHA_C, analysis=lifecycle_module.Analysis())
        lifecycle.decide(case_id=first.case_id, actor_user_id="manager", decision="approve", reason="Fachlich gepr?ft")
        first = lifecycle.activate(case_id=first.case_id)

        second_kb = governance.request_knowledgebase_change(
            "portal", "create", payload={"slug": "verkauf", "label": "Verkauf"}
        ).knowledgebase_id
        governance.grant_access("portal", "employee", second_kb, can_read=True, can_upload=True)
        duplicate = lifecycle.submit(
            uploaded_by_user_id="employee", owner_user_id="employee", target_knowledgebase_id=second_kb,
            title="Doppelter Upload", original_filename="duplicate.docx", original_file_id="dup-file",
            original_sha256="d" * 64, valid_workdays=60, confidentiality="restricted",
        )
        lifecycle.record_analysis(
            case_id=duplicate.case_id, normalized_sha256="e" * 64, markdown_sha256="f" * 64,
            analysis=lifecycle_module.Analysis(exact_duplicate_document_id=first.document_id,
                                               cross_kb_matches=(first.document_id,)),
        )
        lifecycle.choose_action(case_id=duplicate.case_id, actor_user_id="employee", action="publish_existing")
        lifecycle.decide(case_id=duplicate.case_id, actor_user_id="manager", decision="approve",
                         reason="Zusätzliche Veröffentlichung fachlich geprüft")
        ready = lifecycle.decide(case_id=duplicate.case_id, actor_user_id="admin", decision="approve",
                                 reason="Zus?tzliche Ver?ffentlichung fachlich gepr?ft")
        assert ready.status == "ready_to_activate"
        published, target_version_id, previous_status = lifecycle.publish_existing(case_id=duplicate.case_id)
        assert target_version_id == first.version_id
        assert previous_status is None
        assert published.status == "active"
        assert lifecycle.active_version(first.document_id) == first.version_id
        assert lifecycle.active_version(duplicate.document_id) is None
        assert lifecycle.version_record(duplicate.version_id)["status"] == "withdrawn_duplicate"
        with governance.store.connect() as db:
            publication = db.execute(
                "SELECT status FROM document_publications WHERE document_id=? AND knowledgebase_id=?",
                (first.document_id, second_kb),
            ).fetchone()
        assert publication["status"] == "active"
        rolled_back = lifecycle.rollback_existing_publication(
            case_id=duplicate.case_id, previous_status=previous_status, reason="Index nicht verf?gbar"
        )
        assert rolled_back.status == "ready_to_activate"
        with governance.store.connect() as db:
            assert db.execute(
                "SELECT 1 FROM document_publications WHERE document_id=? AND knowledgebase_id=?",
                (first.document_id, second_kb),
            ).fetchone() is None


def test_real_upload_is_bound_to_selected_version_candidate_before_replacement():
    with tempfile.TemporaryDirectory() as directory:
        governance, lifecycle, kb_id = setup(Path(directory))
        first = submit(lifecycle, kb_id)
        lifecycle.record_analysis(case_id=first.case_id, normalized_sha256=SHA_B,
                                  markdown_sha256=SHA_C, analysis=lifecycle_module.Analysis())
        lifecycle.decide(case_id=first.case_id, actor_user_id="manager", decision="approve", reason="Fachlich gepr?ft")
        first = lifecycle.activate(case_id=first.case_id)

        draft = submit(lifecycle, kb_id, sha="d" * 64)
        assert draft.document_id != first.document_id
        lifecycle.record_analysis(
            case_id=draft.case_id, normalized_sha256="e" * 64, markdown_sha256="f" * 64,
            analysis=lifecycle_module.Analysis(
                same_kb_similarity="very_high", version_candidate_document_ids=(first.document_id,)
            ),
        )
        bound = lifecycle.bind_replacement(
            case_id=draft.case_id, target_document_id=first.document_id, actor_user_id="employee"
        )
        assert bound.document_id == first.document_id
        assert bound.owner_user_id == first.owner_user_id
        version = lifecycle.version_record(draft.version_id)
        assert version["previous_version_id"] == first.version_id
        assert version["document_id"] == first.document_id
        with governance.store.connect() as db:
            assert db.execute("SELECT 1 FROM canonical_documents WHERE document_id=?", (draft.document_id,)).fetchone() is None
        pending = lifecycle.choose_action(case_id=draft.case_id, actor_user_id="employee", action="replace")
        assert pending.status == "pending_manager_approval"


def test_contradicting_version_replacement_needs_manager_but_no_extra_admin():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, kb_id = setup(Path(directory))
        first = submit(lifecycle, kb_id, title="KAHLE KI Policy v1.4")
        lifecycle.record_analysis(
            case_id=first.case_id, normalized_sha256=SHA_B,
            markdown_sha256=SHA_C, analysis=lifecycle_module.Analysis(),
        )
        lifecycle.decide(
            case_id=first.case_id, actor_user_id="manager",
            decision="approve", reason="Erstfassung",
        )
        first = lifecycle.activate(case_id=first.case_id)

        draft = submit(
            lifecycle, kb_id, sha="d" * 64, title="KAHLE KI Policy v1.5",
        )
        lifecycle.record_analysis(
            case_id=draft.case_id, normalized_sha256="e" * 64,
            markdown_sha256="f" * 64,
            analysis=lifecycle_module.Analysis(
                same_kb_similarity="very_high",
                version_candidate_document_ids=(first.document_id,),
                contradiction_document_ids=(first.document_id,),
            ),
        )
        lifecycle.bind_replacement(
            case_id=draft.case_id, target_document_id=first.document_id,
            actor_user_id="employee",
        )
        pending = lifecycle.choose_action(
            case_id=draft.case_id, actor_user_id="employee", action="replace",
        )
        assert pending.title == "KAHLE KI Policy v1.5"
        assert pending.requires_admin is False
        approved = lifecycle.decide(
            case_id=draft.case_id, actor_user_id="manager",
            decision="approve", reason="Änderungen fachlich geprüft",
        )
        assert approved.status == "ready_to_activate"
        activated = lifecycle.activate(case_id=draft.case_id)
        assert activated.title == "KAHLE KI Policy v1.5"
        assert lifecycle.active_version(first.document_id) == draft.version_id
        assert lifecycle.version_record(first.version_id)["status"] == "superseded"


def test_security_finding_on_replacement_still_requires_admin():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, kb_id = setup(Path(directory))
        first = submit(lifecycle, kb_id)
        lifecycle.record_analysis(
            case_id=first.case_id, normalized_sha256=SHA_B,
            markdown_sha256=SHA_C, analysis=lifecycle_module.Analysis(),
        )
        lifecycle.decide(
            case_id=first.case_id, actor_user_id="manager",
            decision="approve", reason="Erstfassung",
        )
        first = lifecycle.activate(case_id=first.case_id)
        draft = submit(lifecycle, kb_id, sha="d" * 64)
        lifecycle.record_analysis(
            case_id=draft.case_id, normalized_sha256="e" * 64,
            markdown_sha256="f" * 64,
            analysis=lifecycle_module.Analysis(
                version_candidate_document_ids=(first.document_id,),
                prompt_injection_risk="medium",
            ),
        )
        lifecycle.bind_replacement(
            case_id=draft.case_id, target_document_id=first.document_id,
            actor_user_id="employee",
        )
        pending = lifecycle.choose_action(
            case_id=draft.case_id, actor_user_id="employee", action="replace",
        )
        assert pending.requires_admin is True


def test_any_prompt_injection_signal_requires_manager_then_admin():
    with tempfile.TemporaryDirectory() as directory:
        _, lifecycle, kb_id = setup(Path(directory))
        case = submit(lifecycle, kb_id)
        flagged = lifecycle.record_analysis(
            case_id=case.case_id, normalized_sha256=SHA_B, markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(prompt_injection_risk="medium"),
        )
        assert flagged.status == "pending_manager_approval"
        assert flagged.requires_admin is True
        assert lifecycle.tasks_for("employee") == []
        assert lifecycle.tasks_for("admin") == []
        assert lifecycle.tasks_for("manager")[0].case_id == flagged.case_id
        approved = lifecycle.decide(
            case_id=flagged.case_id, actor_user_id="manager", decision="approve",
            reason="Fachlich vorgeprüft",
        )
        assert approved.status == "pending_admin_approval"
        assert lifecycle.tasks_for("admin")[0].case_id == flagged.case_id


def test_workday_expiry_uses_dynamic_niedersachsen_holidays_after_2026():
    # 26 March 2027 is Good Friday, 29 March is Easter Monday.
    assert lifecycle_module.add_workdays(date(2027, 3, 25), 1) == date(2027, 3, 30)


def test_workdays_until_is_the_inverse_of_add_workdays():
    start = date(2026, 8, 10)  # Monday
    for workdays in (1, 5, 22, 60):
        target = lifecycle_module.add_workdays(start, workdays)
        assert lifecycle_module.workdays_until(start, target) == workdays


def test_workdays_until_skips_weekends_and_niedersachsen_holidays():
    # 26 March 2027 is Good Friday, 29 March is Easter Monday.
    assert lifecycle_module.workdays_until(date(2027, 3, 25), date(2027, 3, 30)) == 1


def test_workdays_until_shortens_rather_than_extends_on_a_non_workday():
    # Saturday resolves to the preceding Friday, never beyond it.
    friday = lifecycle_module.workdays_until(date(2026, 8, 10), date(2026, 8, 14))
    saturday = lifecycle_module.workdays_until(date(2026, 8, 10), date(2026, 8, 15))
    assert saturday == friday == 4


def test_workdays_until_rejects_past_dates_and_more_than_sixty_workdays():
    for start, target in (
        (date(2026, 8, 10), date(2026, 8, 10)),
        (date(2026, 8, 10), date(2026, 8, 7)),
    ):
        try:
            lifecycle_module.workdays_until(start, target)
        except lifecycle_module.LifecycleError as error:
            assert str(error) == "valid_until_not_in_future"
        else:
            raise AssertionError("past date was accepted")

    too_far = lifecycle_module.add_workdays(date(2026, 8, 10), 60) + timedelta(days=1)
    try:
        lifecycle_module.workdays_until(date(2026, 8, 10), too_far)
    except lifecycle_module.LifecycleError as error:
        assert str(error) == "valid_workdays_out_of_range"
    else:
        raise AssertionError("more than 60 workdays was accepted")


def test_admins_also_see_their_own_open_uploads():
    """
    Ein Admin, der selbst hochlaedt, muss seinen Vorgang wiederfinden. Vorher
    lieferte tasks_for fuer Admins ausschliesslich die Eskalationsliste; der
    eigene Upload wartete unsichtbar auf eine Entscheidung und blieb Entwurf.
    """
    with tempfile.TemporaryDirectory() as directory:
        governance, lifecycle, knowledgebase_id = setup(Path(directory))
        case = lifecycle.submit(
            uploaded_by_user_id="admin", owner_user_id="admin",
            target_knowledgebase_id=knowledgebase_id, title="Eigener Upload",
            original_filename="eigen.md", original_file_id="eigen",
            original_sha256=SHA_A, valid_workdays=30, confidentiality="internal",
        )
        checked = lifecycle.record_analysis(
            case_id=case.case_id, normalized_sha256=SHA_B, markdown_sha256=SHA_C,
            analysis=lifecycle_module.Analysis(),
        )
        assert checked.status == "pending_manager_approval"
        assert case.case_id not in {task.case_id for task in lifecycle.tasks_for("admin")}
        assert case.case_id in {task.case_id for task in lifecycle.tasks_for("portal")}
