from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, APP / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


governance_module = load("portal_governance")
lifecycle_module = load("document_lifecycle")
ownership_module = load("ownership")


def test_deactivated_owner_creates_task_and_new_owner_must_confirm():
    with tempfile.TemporaryDirectory() as directory:
        store = governance_module.SQLiteGovernanceStore(Path(directory) / "portal.sqlite3")
        ids = iter(["kb-request", "kb", "document", "version", "case", "task"])
        governance = governance_module.PortalGovernance(store, identifier=lambda: next(ids))
        governance.sync_identity(user_id="admin", email="admin@kahle.de", display_name="Admin", bootstrap_portal_admin=True)
        governance.sync_identity(user_id="manager", email="manager@kahle.de", display_name="Leitung")
        governance.sync_identity(user_id="owner", email="owner@kahle.de", display_name="Owner")
        governance.sync_identity(user_id="new-owner", email="new@kahle.de", display_name="Neu")
        governance.set_role("admin", "manager", "manager")
        governance.assign_manager("admin", "owner", "manager")
        kb = governance.request_knowledgebase_change("admin", "create", payload={"slug": "service", "label": "Service"})
        governance.grant_access("admin", "owner", kb.knowledgebase_id, can_read=True, can_upload=True)
        lifecycle = lifecycle_module.DocumentLifecycle(store, governance, identifier=lambda: next(ids))
        submitted = lifecycle.submit(
            uploaded_by_user_id="owner", owner_user_id="owner", target_knowledgebase_id=kb.knowledgebase_id,
            title="Test", original_filename="test.md", original_file_id="file", original_sha256="a" * 64,
            valid_workdays=60, confidentiality="internal",
        )
        with store.connect() as db:
            db.execute("UPDATE canonical_documents SET active_version_id=? WHERE document_id=?", (submitted.version_id, submitted.document_id))
            db.execute("UPDATE document_versions SET status='active' WHERE version_id=?", (submitted.version_id,))

        ownership = ownership_module.OwnershipService(store, governance, identifier=lambda: next(ids))
        governance.set_active("admin", "owner", False)
        created = ownership.create_for_deactivated_owner("owner", "admin")
        assert created == ["task"]
        assert ownership.tasks_for("manager")[0]["document_id"] == submitted.document_id

        ownership.propose("task", "admin", "new-owner", "Neue fachliche ZustÃ¤ndigkeit")
        assert ownership.tasks_for("new-owner")[0]["status"] == "pending_owner_confirmation"
        assert governance.identity("new-owner").active
        assert ownership.confirm("task", "new-owner", True, "Ich Ã¼bernehme die Verantwortung") == "completed"
        with store.connect() as db:
            owner = db.execute("SELECT owner_user_id FROM canonical_documents WHERE document_id=?", (submitted.document_id,)).fetchone()
        assert owner["owner_user_id"] == "new-owner"


def test_unrelated_manager_cannot_change_another_owners_document():
    with tempfile.TemporaryDirectory() as directory:
        store = governance_module.SQLiteGovernanceStore(Path(directory) / "portal.sqlite3")
        governance = governance_module.PortalGovernance(store)
        governance.sync_identity(user_id="admin", email="admin@kahle.de", display_name="Admin", bootstrap_portal_admin=True)
        governance.sync_identity(user_id="manager", email="manager@kahle.de", display_name="Leitung")
        governance.sync_identity(user_id="other-manager", email="other@kahle.de", display_name="Andere Leitung")
        governance.sync_identity(user_id="owner", email="owner@kahle.de", display_name="Owner")
        governance.set_role("admin", "manager", "manager")
        governance.set_role("admin", "other-manager", "manager")
        governance.assign_manager("admin", "owner", "manager")
        lifecycle_module.DocumentLifecycle(store, governance)
        with store.connect() as db:
            db.execute("INSERT INTO canonical_documents VALUES ('doc','Titel','owner','internal',NULL,'now','now')")
        changes_module = load("document_changes")
        changes = changes_module.DocumentChangeService(store, governance)
        try:
            changes.request_renewal("doc", "other-manager", "Nicht zustÃ¤ndig", True)
            raise AssertionError("unrelated manager must be rejected")
        except changes_module.DocumentChangeError as exc:
            assert str(exc) == "renewal_forbidden"



def test_initial_owner_proposal_pauses_case_until_explicit_confirmation():
    with tempfile.TemporaryDirectory() as directory:
        store = governance_module.SQLiteGovernanceStore(Path(directory) / "portal.sqlite3")
        governance = governance_module.PortalGovernance(store)
        governance.sync_identity(user_id="admin", email="admin@kahle.de", display_name="Admin", bootstrap_portal_admin=True)
        governance.sync_identity(user_id="uploader", email="up@kahle.de", display_name="Uploader")
        governance.sync_identity(user_id="new-owner", email="owner@kahle.de", display_name="Owner")
        governance.sync_identity(user_id="manager", email="lead@kahle.de", display_name="Leitung")
        governance.set_role("admin", "manager", "manager")
        governance.assign_manager("admin", "new-owner", "manager")
        kb = governance.request_knowledgebase_change("admin", "create", payload={"slug": "verkauf", "label": "Verkauf"})
        governance.grant_access("admin", "uploader", kb.knowledgebase_id, can_read=True, can_upload=True)
        lifecycle = lifecycle_module.DocumentLifecycle(store, governance)
        submitted = lifecycle.submit(
            uploaded_by_user_id="uploader", owner_user_id="uploader", target_knowledgebase_id=kb.knowledgebase_id,
            title="Test", original_filename="test.md", original_file_id="file", original_sha256="b" * 64,
            valid_workdays=60, confidentiality="internal",
        )
        with store.connect() as db:
            db.execute("UPDATE document_cases SET status='pending_employee_decision' WHERE case_id=?", (submitted.case_id,))
            db.execute("UPDATE document_versions SET status='pending_employee_decision' WHERE version_id=?", (submitted.version_id,))
        ownership = ownership_module.OwnershipService(store, governance)
        ownership.set_proposal_permission("admin", "uploader", True)
        assert ownership.may_propose_other("uploader")
        task = ownership.create_initial_proposal(submitted.document_id, submitted.case_id, "uploader", "new-owner")
        assert lifecycle.submission(submitted.case_id).status == "pending_owner_confirmation"
        ownership.confirm(task, "new-owner", True, "Verantwortung gepr?ft und ?bernommen")
        resumed = lifecycle.submission(submitted.case_id)
        assert resumed.status == "pending_employee_decision"
        assert resumed.owner_user_id == "new-owner"
        assert resumed.manager_user_id == "manager"
