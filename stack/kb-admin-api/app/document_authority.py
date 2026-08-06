from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Callable

try:
    from .portal_governance import PortalGovernance, SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import PortalGovernance, SQLiteGovernanceStore


class AuthorityError(ValueError):
    pass


AUTHORITY_TYPES = {
    "legal_or_regulatory": 1,
    "manufacturer_or_importer": 2,
    "executive_policy": 3,
    "department_policy": 4,
    "process_or_work_instruction": 5,
    "information_or_training": 6,
}
RELATION_TYPES = {"supersedes", "overrides", "applies_only_if", "related_to"}


class DocumentAuthorityService:
    def __init__(
        self, store: SQLiteGovernanceStore, governance: PortalGovernance, *,
        now: Callable[[], str] | None = None, identifier: Callable[[], str] | None = None,
    ):
        self.store, self.governance = store, governance
        self.now = now or (lambda: datetime.now().astimezone().isoformat())
        self.identifier = identifier or (lambda: str(uuid.uuid4()))
        with self.store.connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS document_authority_relations (
                    relation_id TEXT PRIMARY KEY,
                    source_document_id TEXT NOT NULL REFERENCES canonical_documents(document_id),
                    target_document_id TEXT NOT NULL REFERENCES canonical_documents(document_id),
                    relation_type TEXT NOT NULL,
                    condition_text TEXT,
                    reason TEXT NOT NULL,
                    created_by TEXT NOT NULL REFERENCES portal_users(user_id),
                    created_at TEXT NOT NULL,
                    UNIQUE(source_document_id,target_document_id,relation_type)
                )"""
            )

    def view(self, actor_user_id: str, document_id: str) -> dict[str, Any]:
        self.governance.identity(actor_user_id)
        with self.store.connect() as db:
            metadata = db.execute(
                "SELECT * FROM document_metadata WHERE document_id=?", (document_id,)
            ).fetchone()
            if not metadata:
                raise AuthorityError("unknown_document")
            relations = db.execute(
                "SELECT * FROM document_authority_relations WHERE source_document_id=? OR target_document_id=? "
                "ORDER BY created_at", (document_id, document_id),
            ).fetchall()
        return {"metadata": {**dict(metadata), "scope": json.loads(metadata["scope_json"])},
                "relations": [dict(row) for row in relations]}

    def update(self, actor_user_id: str, document_id: str, authority_type: str,
               scope: dict[str, Any], reason: str) -> dict[str, Any]:
        actor = self.governance.identity(actor_user_id)
        if actor.role not in {"admin", "portal_admin"}:
            raise AuthorityError("admin_required")
        if authority_type not in AUTHORITY_TYPES or len(reason.strip()) < 3:
            raise AuthorityError("authority_type_and_reason_required")
        with self.store.connect() as db:
            result = db.execute(
                "UPDATE document_metadata SET authority_type=?, authority_level=?, scope_json=? WHERE document_id=?",
                (authority_type, AUTHORITY_TYPES[authority_type], json.dumps(scope, ensure_ascii=False, sort_keys=True), document_id),
            )
            if not result.rowcount:
                raise AuthorityError("unknown_document")
            self._event(db, document_id, actor_user_id, "authority_updated", {
                "authority_type": authority_type, "authority_level": AUTHORITY_TYPES[authority_type],
                "scope": scope, "reason": reason.strip(),
            })
        return self.view(actor_user_id, document_id)

    def relate(self, actor_user_id: str, source_document_id: str, target_document_id: str,
               relation_type: str, condition_text: str, reason: str) -> str:
        actor = self.governance.identity(actor_user_id)
        if actor.role not in {"admin", "portal_admin"}:
            raise AuthorityError("admin_required")
        if source_document_id == target_document_id or relation_type not in RELATION_TYPES:
            raise AuthorityError("invalid_authority_relation")
        if relation_type == "applies_only_if" and len(condition_text.strip()) < 3:
            raise AuthorityError("relation_condition_required")
        if len(reason.strip()) < 3:
            raise AuthorityError("relation_reason_required")
        relation_id = self.identifier()
        try:
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO document_authority_relations VALUES (?,?,?,?,?,?,?,?)",
                    (relation_id, source_document_id, target_document_id, relation_type,
                     condition_text.strip() or None, reason.strip(), actor_user_id, self.now()),
                )
                self._event(db, source_document_id, actor_user_id, "authority_relation_created", {
                    "target_document_id": target_document_id, "relation_type": relation_type,
                    "condition": condition_text.strip(), "reason": reason.strip(),
                })
        except Exception as exc:
            if "FOREIGN KEY" in str(exc) or "UNIQUE" in str(exc):
                raise AuthorityError("invalid_or_duplicate_authority_relation") from exc
            raise
        return relation_id

    def _event(self, db, document_id: str, actor_user_id: str, event_type: str, details: dict) -> None:
        case = db.execute(
            "SELECT case_id FROM document_cases WHERE document_id=? ORDER BY created_at DESC LIMIT 1",
            (document_id,),
        ).fetchone()
        if case:
            db.execute(
                "INSERT INTO document_events(case_id,actor_user_id,event_type,details_json,created_at) VALUES (?,?,?,?,?)",
                (case["case_id"], actor_user_id, event_type,
                 json.dumps(details, ensure_ascii=False, sort_keys=True), self.now()),
            )
