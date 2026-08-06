from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Callable

try:
    from .portal_governance import PortalGovernance, SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import PortalGovernance, SQLiteGovernanceStore


class OwnershipError(ValueError):
    pass


class OwnershipService:
    """Owns explicit, confirmed reassignment of canonical document ownership."""

    def __init__(
        self,
        store: SQLiteGovernanceStore,
        governance: PortalGovernance,
        *,
        now: Callable[[], str] | None = None,
        identifier: Callable[[], str] | None = None,
    ):
        self.store = store
        self.governance = governance
        self.now = now or (lambda: datetime.now().astimezone().isoformat())
        self.identifier = identifier or (lambda: str(uuid.uuid4()))
        with self.store.connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS owner_reassignment_tasks (
                    task_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    previous_owner_user_id TEXT NOT NULL,
                    manager_user_id TEXT,
                    proposed_owner_user_id TEXT,
                    created_by TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(document_id, status)
                )"""
            )

    def create_for_deactivated_owner(self, owner_user_id: str, actor_user_id: str) -> list[str]:
        stamp = self.now()
        with self.store.connect() as db:
            owner = db.execute(
                "SELECT manager_user_id FROM portal_users WHERE user_id=?", (owner_user_id,)
            ).fetchone()
            documents = db.execute(
                "SELECT document_id FROM canonical_documents "
                "WHERE owner_user_id=? AND active_version_id IS NOT NULL",
                (owner_user_id,),
            ).fetchall()
            created: list[str] = []
            for document in documents:
                existing = db.execute(
                    "SELECT task_id FROM owner_reassignment_tasks "
                    "WHERE document_id=? AND status IN ('open','pending_owner_confirmation')",
                    (document["document_id"],),
                ).fetchone()
                if existing:
                    continue
                task_id = self.identifier()
                db.execute(
                    "INSERT INTO owner_reassignment_tasks VALUES (?,?,?,?,NULL,?,'open',?,?,?)",
                    (
                        task_id,
                        document["document_id"],
                        owner_user_id,
                        owner["manager_user_id"] if owner else None,
                        actor_user_id,
                        "Owner wurde deaktiviert; keine automatische Eigentumsübertragung.",
                        stamp,
                        stamp,
                    ),
                )
                created.append(task_id)
        return created

    def tasks_for(self, actor_user_id: str) -> list[dict]:
        actor = self.governance.identity(actor_user_id)
        with self.store.connect() as db:
            if actor.role in {"admin", "portal_admin"}:
                rows = db.execute(
                    "SELECT * FROM owner_reassignment_tasks WHERE status!='completed' ORDER BY created_at"
                ).fetchall()
            elif actor.role == "manager":
                rows = db.execute(
                    "SELECT * FROM owner_reassignment_tasks WHERE manager_user_id=? "
                    "AND status!='completed' ORDER BY created_at",
                    (actor_user_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM owner_reassignment_tasks "
                    "WHERE proposed_owner_user_id=? AND status='pending_owner_confirmation' "
                    "ORDER BY created_at",
                    (actor_user_id,),
                ).fetchall()
        return [dict(row) for row in rows]

    def propose(self, task_id: str, actor_user_id: str, proposed_owner_user_id: str, reason: str) -> None:
        actor = self.governance.identity(actor_user_id)
        proposed = self.governance.identity(proposed_owner_user_id)
        if actor.role not in {"admin", "portal_admin"}:
            raise OwnershipError("admin_required")
        if not proposed.active or len(reason.strip()) < 3:
            raise OwnershipError("active_owner_and_reason_required")
        with self.store.connect() as db:
            task = db.execute(
                "SELECT * FROM owner_reassignment_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if not task or task["status"] != "open":
                raise OwnershipError("ownership_task_not_open")
            db.execute(
                "UPDATE owner_reassignment_tasks SET proposed_owner_user_id=?, "
                "status='pending_owner_confirmation', reason=?, updated_at=? WHERE task_id=?",
                (proposed_owner_user_id, reason.strip(), self.now(), task_id),
            )
            self._event(db, task["document_id"], actor_user_id, "owner_reassignment_proposed", {
                "previous_owner_user_id": task["previous_owner_user_id"],
                "proposed_owner_user_id": proposed_owner_user_id,
                "reason": reason.strip(),
            })

    def confirm(self, task_id: str, actor_user_id: str, accept: bool, reason: str) -> str:
        if len(reason.strip()) < 3:
            raise OwnershipError("confirmation_reason_required")
        with self.store.connect() as db:
            task = db.execute(
                "SELECT * FROM owner_reassignment_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if not task or task["status"] != "pending_owner_confirmation":
                raise OwnershipError("ownership_confirmation_not_pending")
            if task["proposed_owner_user_id"] != actor_user_id:
                raise OwnershipError("proposed_owner_required")
            if accept:
                active = db.execute(
                    "SELECT active FROM portal_users WHERE user_id=?", (actor_user_id,)
                ).fetchone()
                if not active or not active["active"]:
                    raise OwnershipError("proposed_owner_inactive")
                db.execute(
                    "UPDATE canonical_documents SET owner_user_id=?, updated_at=? WHERE document_id=?",
                    (actor_user_id, self.now(), task["document_id"]),
                )
                status, event = "completed", "owner_reassignment_confirmed"
            else:
                status, event = "open", "owner_reassignment_rejected"
            db.execute(
                "UPDATE owner_reassignment_tasks SET status=?, proposed_owner_user_id=NULL, "
                "reason=?, updated_at=? WHERE task_id=?",
                (status, reason.strip(), self.now(), task_id),
            )
            self._event(db, task["document_id"], actor_user_id, event, {"reason": reason.strip()})
        return status

    def _event(self, db, document_id: str, actor_user_id: str, event_type: str, details: dict) -> None:
        case = db.execute(
            "SELECT case_id FROM document_cases WHERE document_id=? ORDER BY created_at DESC LIMIT 1",
            (document_id,),
        ).fetchone()
        if case:
            db.execute(
                "INSERT INTO document_events(case_id,actor_user_id,event_type,details_json,created_at) "
                "VALUES (?,?,?,?,?)",
                (case["case_id"], actor_user_id, event_type,
                 json.dumps(details, ensure_ascii=False, sort_keys=True), self.now()),
            )
