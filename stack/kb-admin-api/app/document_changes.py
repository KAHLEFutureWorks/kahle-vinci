from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Callable

try:
    from .document_lifecycle import add_workdays
    from .maintenance import niedersachsen_holidays
    from .portal_governance import PortalGovernance, SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from document_lifecycle import add_workdays
    from maintenance import niedersachsen_holidays
    from portal_governance import PortalGovernance, SQLiteGovernanceStore


class DocumentChangeError(ValueError): pass


class DocumentChangeService:
    LEVELS = {"internal": 0, "restricted": 1, "confidential": 2}

    def __init__(self, store: SQLiteGovernanceStore, governance: PortalGovernance,
                 *, identifier: Callable[[], str] | None = None, today: Callable[[], date] = date.today,
                 now: Callable[[], str] | None = None):
        self.store, self.governance = store, governance
        self.identifier = identifier or (lambda: str(uuid.uuid4())); self.today = today
        self.now = now or (lambda: datetime.now().astimezone().isoformat())
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS document_change_requests (
                request_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, kind TEXT NOT NULL,
                requested_by TEXT NOT NULL, manager_user_id TEXT, desired_value TEXT,
                reason TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")

    def _document(self, document_id: str):
        with self.store.connect() as db:
            row = db.execute("SELECT d.*, u.manager_user_id FROM canonical_documents d JOIN portal_users u ON u.user_id=d.owner_user_id WHERE document_id=?", (document_id,)).fetchone()
        if not row: raise DocumentChangeError("unknown_document")
        return row

    def request_renewal(self, document_id: str, actor_user_id: str, reason: str, confirmed: bool) -> str:
        if not confirmed or len(reason.strip()) < 3: raise DocumentChangeError("renewal_confirmation_and_reason_required")
        document = self._document(document_id); actor = self.governance.identity(actor_user_id)
        allowed_manager = actor.role == "manager" and actor_user_id == document["manager_user_id"]
        if actor_user_id != document["owner_user_id"] and not allowed_manager and actor.role not in {"admin","portal_admin"}:
            raise DocumentChangeError("renewal_forbidden")
        request_id=self.identifier(); status="pending_admin" if actor.role in {"admin","portal_admin"} else "pending_manager"
        if status == "pending_manager" and not document["manager_user_id"]: status="pending_admin"
        with self.store.connect() as db:
            db.execute("INSERT INTO document_change_requests VALUES (?,?,'renewal',?,?,NULL,?,?,?,?)",(request_id,document_id,actor_user_id,document["manager_user_id"],reason.strip(),status,self.now(),self.now()))
        return request_id

    def request_confidentiality(self, document_id: str, actor_user_id: str, desired: str, reason: str) -> str:
        if desired not in self.LEVELS or len(reason.strip()) < 3: raise DocumentChangeError("classification_reason_required")
        document=self._document(document_id); actor=self.governance.identity(actor_user_id)
        allowed_manager = actor.role == "manager" and actor_user_id == document["manager_user_id"]
        if actor_user_id != document["owner_user_id"] and not allowed_manager and actor.role not in {"admin","portal_admin"}:
            raise DocumentChangeError("classification_forbidden")
        request_id=self.identifier(); downgrade=self.LEVELS[desired] < self.LEVELS[document["confidentiality"]]
        status="approved" if actor.role in {"admin","portal_admin"} or not downgrade else "pending_admin"
        with self.store.connect() as db:
            db.execute("INSERT INTO document_change_requests VALUES (?,?,'confidentiality',?,?,?, ?,?,?,?)",(request_id,document_id,actor_user_id,document["manager_user_id"],desired,reason.strip(),status,self.now(),self.now()))
            if status == "approved":
                self._apply_confidentiality(db, document_id, desired, actor_user_id, reason)
                self._event(db, document_id, actor_user_id, "confidentiality_changed", {
                    "before": document["confidentiality"], "after": desired, "reason": reason.strip(),
                })
        return request_id

    def decide(self, request_id: str, actor_user_id: str, approve: bool, reason: str) -> str:
        if len(reason.strip()) < 3: raise DocumentChangeError("decision_reason_required")
        actor=self.governance.identity(actor_user_id)
        with self.store.connect() as db:
            request=db.execute("SELECT * FROM document_change_requests WHERE request_id=?",(request_id,)).fetchone()
            if not request: raise DocumentChangeError("unknown_document_change")
            if request["status"] == "pending_manager":
                if actor_user_id != request["manager_user_id"]: raise DocumentChangeError("manager_required")
                if not approve:
                    next_status="rejected"
                elif request["kind"] == "renewal":
                    publication_count = db.execute(
                        "SELECT COUNT(*) FROM document_publications "
                        "WHERE document_id=? AND status!='inactive'",
                        (request["document_id"],),
                    ).fetchone()[0]
                    next_status="pending_admin" if publication_count > 1 else "approved"
                else:
                    next_status="pending_admin"
            elif request["status"] == "pending_admin":
                if actor.role not in {"admin","portal_admin"}: raise DocumentChangeError("admin_required")
                next_status="approved" if approve else "rejected"
            else: raise DocumentChangeError("document_change_not_pending")
            db.execute("UPDATE document_change_requests SET status=?, updated_at=? WHERE request_id=?",(next_status,self.now(),request_id))
            if next_status == "approved":
                if request["kind"] == "renewal":
                    valid_until=add_workdays(self.today(),60,niedersachsen_holidays(self.today().year)|niedersachsen_holidays(self.today().year+1))
                    db.execute("UPDATE document_versions SET valid_until=? WHERE version_id=(SELECT active_version_id FROM canonical_documents WHERE document_id=?)",(valid_until.isoformat(),request["document_id"]))
                else: self._apply_confidentiality(db,request["document_id"],request["desired_value"],actor_user_id,reason)
                self._event(db, request["document_id"], actor_user_id, "document_change_approved", {
                    "kind": request["kind"], "reason": reason.strip(),
                })
        return next_status

    def _apply_confidentiality(self, db, document_id: str, desired: str, actor: str, reason: str) -> None:
        db.execute("UPDATE canonical_documents SET confidentiality=?, updated_at=? WHERE document_id=?",(desired,self.now(),document_id))

    def _event(self, db, document_id: str, actor_user_id: str, event_type: str, details: dict) -> None:
        case=db.execute("SELECT case_id FROM document_cases WHERE document_id=? ORDER BY created_at DESC LIMIT 1",(document_id,)).fetchone()
        if case:
            db.execute("INSERT INTO document_events(case_id,actor_user_id,event_type,details_json,created_at) VALUES (?,?,?,?,?)",
                       (case["case_id"],actor_user_id,event_type,json.dumps(details, ensure_ascii=False, sort_keys=True),self.now()))

    def pending_for(self, actor_user_id: str) -> list[dict]:
        actor=self.governance.identity(actor_user_id)
        with self.store.connect() as db:
            if actor.role in {"admin","portal_admin"}: rows=db.execute("SELECT * FROM document_change_requests WHERE status='pending_admin' ORDER BY created_at").fetchall()
            elif actor.role == "manager": rows=db.execute("SELECT * FROM document_change_requests WHERE status='pending_manager' AND manager_user_id=? ORDER BY created_at",(actor_user_id,)).fetchall()
            else: rows=db.execute("SELECT * FROM document_change_requests WHERE requested_by=? ORDER BY created_at DESC",(actor_user_id,)).fetchall()
        return [dict(row) for row in rows]
