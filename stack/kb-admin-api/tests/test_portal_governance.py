from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "portal_governance.py"
SPEC = importlib.util.spec_from_file_location("portal_governance", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def portal_at(root: Path):
    ids = iter(f"id-{index}" for index in range(1, 100))
    return module.PortalGovernance(
        module.SQLiteGovernanceStore(root / "portal.sqlite3"),
        now=lambda: "2026-08-06T10:00:00+00:00",
        identifier=lambda: next(ids),
    )


def bootstrap(portal):
    owner = portal.sync_identity(
        user_id="owner",
        email="owner@kahle.de",
        display_name="Portal Owner",
        bootstrap_portal_admin=True,
    )
    assert owner.role == "portal_admin"
    portal.sync_identity(user_id="admin", email="admin@kahle.de", display_name="Admin")
    portal.sync_identity(user_id="manager", email="manager@kahle.de", display_name="Leitung")
    portal.sync_identity(user_id="employee", email="employee@kahle.de", display_name="Mitarbeiter")
    portal.set_role("owner", "admin", "admin")
    portal.set_role("owner", "manager", "manager")


def test_role_boundaries_and_last_portal_admin_invariant():
    with tempfile.TemporaryDirectory() as directory:
        portal = portal_at(Path(directory))
        bootstrap(portal)

        try:
            portal.set_role("admin", "employee", "admin")
            raise AssertionError("normal admin must not assign admin roles")
        except module.GovernanceError as exc:
            assert str(exc) == "portal_admin_required"

        try:
            portal.set_role("owner", "owner", "admin")
            raise AssertionError("the final portal admin must remain active")
        except module.GovernanceError as exc:
            assert str(exc) == "last_portal_admin_required"

        portal.set_role("owner", "employee", "portal_admin")
        changed = portal.set_role("owner", "owner", "admin")
        assert changed.role == "admin"


def test_portal_deactivation_is_not_undone_by_identity_sync():
    with tempfile.TemporaryDirectory() as directory:
        portal = portal_at(Path(directory))
        bootstrap(portal)
        portal.set_active("admin", "employee", False)
        synced = portal.sync_identity(
            user_id="employee",
            email="employee@kahle.de",
            display_name="Neuer Anzeigename",
            active=True,
        )
        assert synced.active is False
        assert synced.display_name == "Neuer Anzeigename"

def test_manager_delegation_and_separate_read_upload_access():
    with tempfile.TemporaryDirectory() as directory:
        portal = portal_at(Path(directory))
        bootstrap(portal)
        kb_request = portal.request_knowledgebase_change(
            "owner",
            "create",
            payload={"slug": "service", "label": "Service", "purpose": "Servicewissen"},
        )
        kb_id = kb_request.knowledgebase_id
        assert kb_id

        assigned = portal.assign_manager("admin", "employee", "manager")
        assert assigned.manager_user_id == "manager"
        portal.assign_delegate("admin", "manager", "admin")

        portal.grant_access(
            "admin", "employee", kb_id, can_read=True, can_upload=False
        )
        assert portal.allowed_knowledgebases("employee", "read") == [kb_id]
        assert portal.allowed_knowledgebases("employee", "upload") == []

        portal.grant_access(
            "admin", "employee", kb_id, can_read=True, can_upload=True
        )
        portal.require_access("employee", kb_id, "upload")


def test_admin_prepares_knowledgebase_change_portal_admin_decides():
    with tempfile.TemporaryDirectory() as directory:
        portal = portal_at(Path(directory))
        bootstrap(portal)

        pending = portal.request_knowledgebase_change(
            "admin",
            "create",
            payload={"slug": "verkauf", "label": "Verkauf", "purpose": "Verkaufswissen"},
        )
        assert pending.status == "pending"
        assert pending.knowledgebase_id is None

        approved = portal.decide_knowledgebase_change(
            "owner", pending.request_id, approve=True, reason="Fachbereich bestätigt"
        )
        assert approved.status == "approved"
        assert approved.knowledgebase_id
        assert portal.knowledgebase(approved.knowledgebase_id).label == "Verkauf"

        rename = portal.request_knowledgebase_change(
            "admin",
            "rename",
            knowledgebase_id=approved.knowledgebase_id,
            payload={"label": "Vertrieb"},
        )
        rejected = portal.decide_knowledgebase_change(
            "owner", rename.request_id, approve=False, reason="Bezeichnung bleibt Verkauf"
        )
        assert rejected.status == "rejected"
        assert portal.knowledgebase(approved.knowledgebase_id).label == "Verkauf"

        events = portal.audit_events("admin")
        assert {event["event_type"] for event in events} >= {
            "identity_synced",
            "role_changed",
            "knowledgebase_change_requested",
            "knowledgebase_change_decided",
        }


if __name__ == "__main__":
    test_role_boundaries_and_last_portal_admin_invariant()
    test_portal_deactivation_is_not_undone_by_identity_sync()
    test_manager_delegation_and_separate_read_upload_access()
    test_admin_prepares_knowledgebase_change_portal_admin_decides()
    print("portal governance tests passed")
