from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Literal


Role = Literal["employee", "manager", "admin", "portal_admin"]
AccessKind = Literal["read", "upload"]
ChangeKind = Literal["create", "rename", "archive", "delete"]

ROLES: tuple[Role, ...] = ("employee", "manager", "admin", "portal_admin")
ADMIN_ROLES = {"admin", "portal_admin"}


class GovernanceError(ValueError):
    """A stable, user-safe governance error returned at the module interface."""


@dataclass(frozen=True)
class Identity:
    user_id: str
    email: str
    display_name: str
    active: bool
    role: Role
    manager_user_id: str | None


@dataclass(frozen=True)
class Knowledgebase:
    knowledgebase_id: str
    slug: str
    label: str
    purpose: str
    status: str


@dataclass(frozen=True)
class ChangeRequest:
    request_id: str
    kind: ChangeKind
    knowledgebase_id: str | None
    requested_by: str
    status: str
    payload: dict[str, Any]
    decided_by: str | None
    decision_reason: str | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteGovernanceStore:
    """SQLite adapter for the governance module's internal persistence seam."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS portal_users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    role TEXT NOT NULL DEFAULT 'employee'
                        CHECK (role IN ('employee','manager','admin','portal_admin')),
                    manager_user_id TEXT REFERENCES portal_users(user_id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS manager_delegates (
                    manager_user_id TEXT NOT NULL REFERENCES portal_users(user_id),
                    delegate_user_id TEXT NOT NULL REFERENCES portal_users(user_id),
                    valid_from TEXT,
                    valid_until TEXT,
                    PRIMARY KEY (manager_user_id, delegate_user_id)
                );

                CREATE TABLE IF NOT EXISTS manager_absences (
                    manager_user_id TEXT PRIMARY KEY REFERENCES portal_users(user_id),
                    absent_from TEXT NOT NULL,
                    absent_until TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    updated_by TEXT NOT NULL REFERENCES portal_users(user_id),
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledgebases (
                    knowledgebase_id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    purpose TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','archived','deleted')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledgebase_access (
                    user_id TEXT NOT NULL REFERENCES portal_users(user_id),
                    knowledgebase_id TEXT NOT NULL REFERENCES knowledgebases(knowledgebase_id),
                    can_read INTEGER NOT NULL DEFAULT 0,
                    can_upload INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, knowledgebase_id)
                );

                CREATE TABLE IF NOT EXISTS knowledgebase_change_requests (
                    request_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('create','rename','archive','delete')),
                    knowledgebase_id TEXT REFERENCES knowledgebases(knowledgebase_id),
                    requested_by TEXT NOT NULL REFERENCES portal_users(user_id),
                    status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected')),
                    payload_json TEXT NOT NULL,
                    decided_by TEXT REFERENCES portal_users(user_id),
                    decision_reason TEXT,
                    created_at TEXT NOT NULL,
                    decided_at TEXT
                );

                CREATE TABLE IF NOT EXISTS governance_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS portal_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    updated_by TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_access_read
                    ON knowledgebase_access(user_id, can_read);
                CREATE INDEX IF NOT EXISTS idx_access_upload
                    ON knowledgebase_access(user_id, can_upload);
                CREATE INDEX IF NOT EXISTS idx_change_status
                    ON knowledgebase_change_requests(status, created_at);
                """
            )
            absence_columns = {row["name"] for row in db.execute("PRAGMA table_info(manager_absences)")}
            if "delegate_user_id" not in absence_columns:
                db.execute("ALTER TABLE manager_absences ADD COLUMN delegate_user_id TEXT REFERENCES portal_users(user_id)")


class PortalGovernance:
    """
    Deep module for portal identity, role and knowledgebase governance.

    Callers provide authenticated stable user IDs. This module owns all role
    invariants, manager relationships, read/upload grants, approval rules and
    audit writes. Browser-supplied roles are never accepted at this interface.
    """

    def __init__(
        self,
        store: SQLiteGovernanceStore,
        *,
        now: Callable[[], str] = utc_now,
        identifier: Callable[[], str] = lambda: str(uuid.uuid4()),
    ):
        self.store = store
        self.now = now
        self.identifier = identifier

    def sync_identity(
        self,
        *,
        user_id: str,
        email: str,
        display_name: str,
        active: bool = True,
        bootstrap_portal_admin: bool = False,
    ) -> Identity:
        user_id = self._required(user_id, "user_id")
        email = self._email(email)
        display_name = self._required(display_name, "display_name")
        stamp = self.now()
        with self.store.connect() as db:
            existing = db.execute(
                "SELECT role FROM portal_users WHERE user_id = ?", (user_id,)
            ).fetchone()
            portal_admins = db.execute(
                "SELECT COUNT(*) AS count FROM portal_users WHERE active = 1 AND role = 'portal_admin'"
            ).fetchone()["count"]
            role: Role = (
                existing["role"]
                if existing
                else "portal_admin"
                if bootstrap_portal_admin and portal_admins == 0
                else "employee"
            )
            db.execute(
                """
                INSERT INTO portal_users (
                    user_id, email, display_name, active, role, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    email = excluded.email,
                    display_name = excluded.display_name,
                    updated_at = excluded.updated_at
                """,
                (user_id, email, display_name, int(active), role, stamp, stamp),
            )
            self._audit(
                db,
                user_id,
                "identity_synced",
                "user",
                user_id,
                {"email": email, "active": active},
            )
        return self.identity(user_id)

    def identity(self, user_id: str) -> Identity:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM portal_users WHERE user_id = ?", (user_id,)
            ).fetchone()
        if not row:
            raise GovernanceError("unknown_user")
        return self._identity(row)

    def list_identities(self, actor_user_id: str) -> list[Identity]:
        self._require_role(actor_user_id, ADMIN_ROLES)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM portal_users ORDER BY display_name COLLATE NOCASE, email COLLATE NOCASE"
            ).fetchall()
        return [self._identity(row) for row in rows]

    def setting_bool(self, setting_key: str, *, default: bool = False) -> bool:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT setting_value FROM portal_settings WHERE setting_key=?", (setting_key,),
            ).fetchone()
        return default if not row else row["setting_value"] == "true"

    def set_setting_bool(
        self, actor_user_id: str, setting_key: str, enabled: bool, reason: str,
    ) -> bool:
        actor = self.identity(actor_user_id)
        if actor.role != "portal_admin":
            raise GovernanceError("portal_admin_required")
        if len(reason.strip()) < 3:
            raise GovernanceError("setting_reason_required")
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO portal_settings(setting_key,setting_value,updated_by,updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, "
                "updated_by=excluded.updated_by,updated_at=excluded.updated_at",
                (setting_key, "true" if enabled else "false", actor_user_id, self.now()),
            )
            self._audit(db, actor_user_id, "portal_setting_changed", "portal_setting", setting_key, {
                "enabled": enabled, "reason": reason.strip(),
            })
        return enabled

    def set_role(self, actor_user_id: str, target_user_id: str, role: Role) -> Identity:
        if role not in ROLES:
            raise GovernanceError("invalid_role")
        actor = self.identity(actor_user_id)
        target = self.identity(target_user_id)
        if actor.role == "admin" and (target.role in ADMIN_ROLES or role in ADMIN_ROLES):
            raise GovernanceError("portal_admin_required")
        if actor.role != "portal_admin" and actor.role != "admin":
            raise GovernanceError("admin_required")
        if target.role == "portal_admin" and role != "portal_admin":
            self._ensure_another_portal_admin(target_user_id)
        manager_user_id = target.manager_user_id
        if role == "admin":
            if actor.role != "portal_admin" or actor_user_id == target_user_id:
                candidates = [item for item in self.list_identities(actor_user_id)
                              if item.role == "portal_admin" and item.active and item.user_id != target_user_id]
                if not candidates:
                    raise GovernanceError("admin_portal_manager_required")
                manager_user_id = candidates[0].user_id
            else:
                manager_user_id = actor_user_id
        elif role == "portal_admin":
            manager_user_id = None
        with self.store.connect() as db:
            db.execute(
                "UPDATE portal_users SET role = ?, manager_user_id = ?, updated_at = ? WHERE user_id = ?",
                (role, manager_user_id, self.now(), target_user_id),
            )
            self._audit(
                db,
                actor_user_id,
                "role_changed",
                "user",
                target_user_id,
                {"before": target.role, "after": role},
            )
        return self.identity(target_user_id)

    def set_active(self, actor_user_id: str, target_user_id: str, active: bool) -> Identity:
        self._require_role(actor_user_id, ADMIN_ROLES)
        target = self.identity(target_user_id)
        if target.role == "portal_admin" and not active:
            self._ensure_another_portal_admin(target_user_id)
        with self.store.connect() as db:
            db.execute(
                "UPDATE portal_users SET active = ?, updated_at = ? WHERE user_id = ?",
                (int(active), self.now(), target_user_id),
            )
            self._audit(
                db,
                actor_user_id,
                "user_activation_changed",
                "user",
                target_user_id,
                {"active": active},
            )
        return self.identity(target_user_id)

    def assign_manager(
        self, actor_user_id: str, employee_user_id: str, manager_user_id: str | None
    ) -> Identity:
        self._require_role(actor_user_id, ADMIN_ROLES)
        employee = self.identity(employee_user_id)
        if employee.role == "portal_admin" and manager_user_id is not None:
            raise GovernanceError("portal_admin_manager_not_allowed")
        if employee.role == "admin" and not manager_user_id:
            raise GovernanceError("admin_portal_manager_required")
        if manager_user_id:
            manager = self.identity(manager_user_id)
            if not manager.active or manager.role not in {"manager", "admin", "portal_admin"}:
                raise GovernanceError("invalid_manager")
            if employee_user_id == manager_user_id:
                raise GovernanceError("self_manager_not_allowed")
            if employee.role == "admin" and manager.role != "portal_admin":
                raise GovernanceError("admin_portal_manager_required")
        with self.store.connect() as db:
            db.execute(
                "UPDATE portal_users SET manager_user_id = ?, updated_at = ? WHERE user_id = ?",
                (manager_user_id, self.now(), employee_user_id),
            )
            self._audit(
                db,
                actor_user_id,
                "manager_assigned",
                "user",
                employee_user_id,
                {"manager_user_id": manager_user_id},
            )
        return self.identity(employee_user_id)

    def assign_delegate(
        self,
        actor_user_id: str,
        manager_user_id: str,
        delegate_user_id: str,
        *,
        valid_from: str | None = None,
        valid_until: str | None = None,
    ) -> None:
        self._require_role(actor_user_id, ADMIN_ROLES)
        manager = self.identity(manager_user_id)
        delegate = self.identity(delegate_user_id)
        if manager.role not in {"manager", "admin", "portal_admin"} or not delegate.active:
            raise GovernanceError("invalid_delegate")
        if manager_user_id == delegate_user_id:
            raise GovernanceError("self_delegate_not_allowed")
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO manager_delegates (
                    manager_user_id, delegate_user_id, valid_from, valid_until
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(manager_user_id, delegate_user_id) DO UPDATE SET
                    valid_from = excluded.valid_from,
                    valid_until = excluded.valid_until
                """,
                (manager_user_id, delegate_user_id, valid_from, valid_until),
            )
            self._audit(
                db,
                actor_user_id,
                "delegate_assigned",
                "user",
                manager_user_id,
                {"delegate_user_id": delegate_user_id, "valid_from": valid_from, "valid_until": valid_until},
            )

    def list_delegations(self, actor_user_id: str) -> list[dict[str, Any]]:
        self._require_role(actor_user_id, ADMIN_ROLES)
        with self.store.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM manager_delegates ORDER BY manager_user_id, delegate_user_id").fetchall()]

    def remove_delegate(self, actor_user_id: str, manager_user_id: str, delegate_user_id: str) -> None:
        self._require_role(actor_user_id, ADMIN_ROLES)
        with self.store.connect() as db:
            cursor=db.execute("DELETE FROM manager_delegates WHERE manager_user_id=? AND delegate_user_id=?",(manager_user_id,delegate_user_id))
            if not cursor.rowcount: raise GovernanceError("unknown_delegation")
            self._audit(db,actor_user_id,"delegate_removed","user",manager_user_id,{"delegate_user_id":delegate_user_id})

    def may_approve_for_manager(self, actor_user_id: str, manager_user_id: str | None) -> bool:
        if not manager_user_id:
            return False
        actor = self.identity(actor_user_id)
        if actor.role in ADMIN_ROLES or actor_user_id == manager_user_id:
            return True
        today = self.now()[:10]
        with self.store.connect() as db:
            row = db.execute(
                """SELECT 1 FROM manager_delegates
                   WHERE manager_user_id = ? AND delegate_user_id = ?
                     AND (valid_from IS NULL OR valid_from <= ?)
                     AND (valid_until IS NULL OR valid_until >= ?)""",
                (manager_user_id, actor_user_id, today, today),
            ).fetchone()
        return bool(row)

    def set_absence(
        self, actor_user_id: str, manager_user_id: str,
        absent_from: str | None, absent_until: str | None, reason: str,
        delegate_user_id: str | None = None,
    ) -> None:
        self._require_role(actor_user_id, ADMIN_ROLES)
        manager = self.identity(manager_user_id)
        if manager.role not in {"manager", "admin", "portal_admin"}:
            raise GovernanceError("invalid_manager")
        with self.store.connect() as db:
            if absent_from is None and absent_until is None:
                absence = db.execute(
                    "SELECT delegate_user_id FROM manager_absences WHERE manager_user_id=?",
                    (manager_user_id,),
                ).fetchone()
                db.execute("DELETE FROM manager_absences WHERE manager_user_id=?", (manager_user_id,))
                if absence and absence["delegate_user_id"]:
                    db.execute(
                        "DELETE FROM manager_delegates WHERE manager_user_id=? AND delegate_user_id=?",
                        (manager_user_id, absence["delegate_user_id"]),
                    )
                    self._audit(
                        db, actor_user_id, "delegate_removed", "user", manager_user_id,
                        {"delegate_user_id": absence["delegate_user_id"]},
                    )
                event, details = "manager_absence_removed", {
                    "delegate_user_id": absence["delegate_user_id"] if absence else None,
                }
            else:
                start = self._iso_date(absent_from, "absent_from")
                end = self._iso_date(absent_until, "absent_until")
                if start > end or len(reason.strip()) < 3:
                    raise GovernanceError("invalid_absence")
                if delegate_user_id:
                    delegate = self.identity(delegate_user_id)
                    if not delegate.active or delegate_user_id == manager_user_id:
                        raise GovernanceError("invalid_delegate")
                    db.execute("DELETE FROM manager_delegates WHERE manager_user_id=?", (manager_user_id,))
                    db.execute(
                        "INSERT INTO manager_delegates(manager_user_id,delegate_user_id,valid_from,valid_until) VALUES (?,?,?,?)",
                        (manager_user_id, delegate_user_id, start, end),
                    )
                    self._audit(db, actor_user_id, "delegate_assigned", "user", manager_user_id,
                                {"delegate_user_id":delegate_user_id,"valid_from":start,"valid_until":end})
                else:
                    existing = db.execute(
                        "SELECT delegate_user_id FROM manager_delegates WHERE manager_user_id=? LIMIT 1",
                        (manager_user_id,),
                    ).fetchone()
                    if not existing:
                        raise GovernanceError("manager_delegate_required")
                    delegate_user_id = existing["delegate_user_id"]
                db.execute(
                    "INSERT INTO manager_absences(manager_user_id,absent_from,absent_until,reason,updated_by,updated_at,delegate_user_id) VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT(manager_user_id) DO UPDATE SET absent_from=excluded.absent_from, "
                    "absent_until=excluded.absent_until, reason=excluded.reason, "
                    "updated_by=excluded.updated_by, updated_at=excluded.updated_at, delegate_user_id=excluded.delegate_user_id",
                    (manager_user_id, start, end, reason.strip(), actor_user_id, self.now(), delegate_user_id),
                )
                event, details = "manager_absence_set", {"absent_from": start, "absent_until": end,
                                                          "reason": reason.strip(), "delegate_user_id": delegate_user_id}
            self._audit(db, actor_user_id, event, "user", manager_user_id, details)

    def list_absences(self, actor_user_id: str) -> list[dict[str, Any]]:
        self._require_role(actor_user_id, ADMIN_ROLES)
        with self.store.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM manager_absences ORDER BY absent_from, manager_user_id"
            ).fetchall()]

    @staticmethod
    def _iso_date(value: str | None, field: str) -> str:
        try:
            return date.fromisoformat(str(value or "")).isoformat()
        except ValueError as exc:
            raise GovernanceError(f"{field}_invalid") from exc

    def grant_access(
        self,
        actor_user_id: str,
        target_user_id: str,
        knowledgebase_id: str,
        *,
        can_read: bool,
        can_upload: bool,
    ) -> None:
        self._require_role(actor_user_id, ADMIN_ROLES)
        self.identity(target_user_id)
        self.knowledgebase(knowledgebase_id)
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO knowledgebase_access (
                    user_id, knowledgebase_id, can_read, can_upload, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, knowledgebase_id) DO UPDATE SET
                    can_read = excluded.can_read,
                    can_upload = excluded.can_upload,
                    updated_at = excluded.updated_at
                """,
                (target_user_id, knowledgebase_id, int(can_read), int(can_upload), self.now()),
            )
            self._audit(
                db,
                actor_user_id,
                "knowledgebase_access_changed",
                "knowledgebase",
                knowledgebase_id,
                {"target_user_id": target_user_id, "can_read": can_read, "can_upload": can_upload},
            )

    def allowed_knowledgebases(self, user_id: str, access: AccessKind) -> list[str]:
        if access not in {"read", "upload"}:
            raise GovernanceError("invalid_access_kind")
        user = self.identity(user_id)
        if not user.active:
            return []
        if user.role in ADMIN_ROLES:
            with self.store.connect() as db:
                rows = db.execute(
                    "SELECT knowledgebase_id FROM knowledgebases WHERE status = 'active' ORDER BY slug"
                ).fetchall()
            return [row["knowledgebase_id"] for row in rows]
        column = "can_read" if access == "read" else "can_upload"
        with self.store.connect() as db:
            rows = db.execute(
                f"""
                SELECT a.knowledgebase_id
                FROM knowledgebase_access a
                JOIN knowledgebases k USING (knowledgebase_id)
                WHERE a.user_id = ? AND a.{column} = 1 AND k.status = 'active'
                ORDER BY k.slug
                """,
                (user_id,),
            ).fetchall()
        return [row["knowledgebase_id"] for row in rows]

    def access_for_user(self, actor_user_id: str, target_user_id: str) -> list[dict[str, Any]]:
        self._require_role(actor_user_id, ADMIN_ROLES)
        self.identity(target_user_id)
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT k.knowledgebase_id, k.label,
                          COALESCE(a.can_read, 0) AS can_read, COALESCE(a.can_upload, 0) AS can_upload
                   FROM knowledgebases k
                   LEFT JOIN knowledgebase_access a
                     ON a.knowledgebase_id = k.knowledgebase_id AND a.user_id = ?
                   WHERE k.status = 'active' ORDER BY k.slug""",
                (target_user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def require_access(self, user_id: str, knowledgebase_id: str, access: AccessKind) -> None:
        if knowledgebase_id not in self.allowed_knowledgebases(user_id, access):
            raise GovernanceError(f"knowledgebase_{access}_forbidden")

    def knowledgebase(self, knowledgebase_id: str) -> Knowledgebase:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM knowledgebases WHERE knowledgebase_id = ?", (knowledgebase_id,)
            ).fetchone()
        if not row:
            raise GovernanceError("unknown_knowledgebase")
        return self._knowledgebase(row)

    def list_knowledgebases(self, user_id: str, access: AccessKind = "read") -> list[Knowledgebase]:
        ids = self.allowed_knowledgebases(user_id, access)
        return [self.knowledgebase(item) for item in ids]

    def request_knowledgebase_change(
        self,
        actor_user_id: str,
        kind: ChangeKind,
        *,
        knowledgebase_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ChangeRequest:
        actor = self._require_role(actor_user_id, ADMIN_ROLES)
        if kind not in {"create", "rename", "archive", "delete"}:
            raise GovernanceError("invalid_change_kind")
        clean_payload = self._validate_change(kind, knowledgebase_id, payload or {})
        request_id = self.identifier()
        status = "approved" if actor.role == "portal_admin" else "pending"
        with self.store.connect() as db:
            db.execute(
                """
                INSERT INTO knowledgebase_change_requests (
                    request_id, kind, knowledgebase_id, requested_by, status,
                    payload_json, decided_by, decision_reason, created_at, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    kind,
                    knowledgebase_id,
                    actor_user_id,
                    status,
                    json.dumps(clean_payload, ensure_ascii=False, sort_keys=True),
                    actor_user_id if status == "approved" else None,
                    "portal_admin_direct" if status == "approved" else None,
                    self.now(),
                    self.now() if status == "approved" else None,
                ),
            )
            if status == "approved":
                knowledgebase_id = self._apply_change(db, kind, knowledgebase_id, clean_payload)
                db.execute(
                    "UPDATE knowledgebase_change_requests SET knowledgebase_id = ? WHERE request_id = ?",
                    (knowledgebase_id, request_id),
                )
            self._audit(
                db,
                actor_user_id,
                "knowledgebase_change_requested",
                "knowledgebase_change",
                request_id,
                {"kind": kind, "status": status, "knowledgebase_id": knowledgebase_id},
            )
        return self.change_request(request_id)

    def decide_knowledgebase_change(
        self,
        actor_user_id: str,
        request_id: str,
        *,
        approve: bool,
        reason: str,
    ) -> ChangeRequest:
        self._require_role(actor_user_id, {"portal_admin"})
        reason = self._required(reason, "decision_reason")
        request = self.change_request(request_id)
        if request.status != "pending":
            raise GovernanceError("change_request_not_pending")
        status = "approved" if approve else "rejected"
        knowledgebase_id = request.knowledgebase_id
        with self.store.connect() as db:
            if approve:
                knowledgebase_id = self._apply_change(
                    db, request.kind, request.knowledgebase_id, request.payload
                )
            db.execute(
                """
                UPDATE knowledgebase_change_requests
                SET status = ?, knowledgebase_id = ?, decided_by = ?,
                    decision_reason = ?, decided_at = ?
                WHERE request_id = ?
                """,
                (status, knowledgebase_id, actor_user_id, reason, self.now(), request_id),
            )
            self._audit(
                db,
                actor_user_id,
                "knowledgebase_change_decided",
                "knowledgebase_change",
                request_id,
                {"approved": approve, "reason": reason, "knowledgebase_id": knowledgebase_id},
            )
        return self.change_request(request_id)

    def list_change_requests(self, actor_user_id: str, status: str | None = None) -> list[ChangeRequest]:
        self._require_role(actor_user_id, ADMIN_ROLES)
        query = "SELECT request_id FROM knowledgebase_change_requests"
        values: tuple[Any, ...] = ()
        if status:
            if status not in {"pending", "approved", "rejected"}:
                raise GovernanceError("invalid_change_status")
            query += " WHERE status = ?"; values = (status,)
        query += " ORDER BY created_at DESC"
        with self.store.connect() as db:
            ids = [row["request_id"] for row in db.execute(query, values).fetchall()]
        return [self.change_request(request_id) for request_id in ids]

    def change_request(self, request_id: str) -> ChangeRequest:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM knowledgebase_change_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
        if not row:
            raise GovernanceError("unknown_change_request")
        return ChangeRequest(
            request_id=row["request_id"],
            kind=row["kind"],
            knowledgebase_id=row["knowledgebase_id"],
            requested_by=row["requested_by"],
            status=row["status"],
            payload=json.loads(row["payload_json"]),
            decided_by=row["decided_by"],
            decision_reason=row["decision_reason"],
        )

    def audit_events(self, actor_user_id: str) -> list[dict[str, Any]]:
        self._require_role(actor_user_id, ADMIN_ROLES)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM governance_audit ORDER BY sequence"
            ).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "occurred_at": row["occurred_at"],
                "actor_user_id": row["actor_user_id"],
                "event_type": row["event_type"],
                "subject_type": row["subject_type"],
                "subject_id": row["subject_id"],
                "details": json.loads(row["details_json"]),
            }
            for row in rows
        ]

    def record_audit(
        self, actor_user_id: str, event_type: str, subject_type: str,
        subject_id: str, details: dict[str, Any] | None = None,
    ) -> None:
        """Append an application-level event to the shared audit stream."""
        self.identity(actor_user_id)
        with self.store.connect() as db:
            self._audit(db, actor_user_id, self._required(event_type, "event_type"),
                        self._required(subject_type, "subject_type"),
                        self._required(subject_id, "subject_id"), details or {})

    def _validate_change(
        self, kind: ChangeKind, knowledgebase_id: str | None, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if kind == "create":
            return {
                "slug": self._slug(payload.get("slug")),
                "label": self._required(payload.get("label"), "label"),
                "purpose": str(payload.get("purpose") or "").strip(),
            }
        if not knowledgebase_id:
            raise GovernanceError("knowledgebase_id_required")
        knowledgebase = self.knowledgebase(knowledgebase_id)
        if kind == "rename":
            return {"label": self._required(payload.get("label"), "label")}
        if kind == "archive" and knowledgebase.status != "active":
            raise GovernanceError("knowledgebase_not_active")
        if kind == "delete" and knowledgebase.status != "archived":
            raise GovernanceError("knowledgebase_must_be_archived_first")
        return {}

    def _apply_change(
        self,
        db: sqlite3.Connection,
        kind: ChangeKind,
        knowledgebase_id: str | None,
        payload: dict[str, Any],
    ) -> str:
        stamp = self.now()
        if kind == "create":
            knowledgebase_id = self.identifier()
            try:
                db.execute(
                    """
                    INSERT INTO knowledgebases (
                        knowledgebase_id, slug, label, purpose, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (knowledgebase_id, payload["slug"], payload["label"], payload["purpose"], stamp, stamp),
                )
            except sqlite3.IntegrityError as exc:
                raise GovernanceError("knowledgebase_slug_exists") from exc
            return knowledgebase_id
        if not knowledgebase_id:
            raise GovernanceError("knowledgebase_id_required")
        if kind == "rename":
            db.execute(
                "UPDATE knowledgebases SET label = ?, updated_at = ? WHERE knowledgebase_id = ?",
                (payload["label"], stamp, knowledgebase_id),
            )
        elif kind == "archive":
            db.execute(
                "UPDATE knowledgebases SET status = 'archived', updated_at = ? WHERE knowledgebase_id = ?",
                (stamp, knowledgebase_id),
            )
        elif kind == "delete":
            db.execute(
                "UPDATE knowledgebases SET status = 'deleted', updated_at = ? WHERE knowledgebase_id = ?",
                (stamp, knowledgebase_id),
            )
        return knowledgebase_id

    def _ensure_another_portal_admin(self, excluded_user_id: str) -> None:
        with self.store.connect() as db:
            count = db.execute(
                """
                SELECT COUNT(*) AS count FROM portal_users
                WHERE active = 1 AND role = 'portal_admin' AND user_id != ?
                """,
                (excluded_user_id,),
            ).fetchone()["count"]
        if count < 1:
            raise GovernanceError("last_portal_admin_required")

    def _require_role(self, user_id: str, roles: set[str]) -> Identity:
        user = self.identity(user_id)
        if not user.active:
            raise GovernanceError("inactive_user")
        if user.role not in roles:
            raise GovernanceError("forbidden")
        return user

    def _audit(
        self,
        db: sqlite3.Connection,
        actor_user_id: str,
        event_type: str,
        subject_type: str,
        subject_id: str,
        details: dict[str, Any],
    ) -> None:
        db.execute(
            """
            INSERT INTO governance_audit (
                occurred_at, actor_user_id, event_type, subject_type, subject_id, details_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self.now(),
                actor_user_id,
                event_type,
                subject_type,
                subject_id,
                json.dumps(details, ensure_ascii=False, sort_keys=True),
            ),
        )

    @staticmethod
    def _identity(row: sqlite3.Row) -> Identity:
        return Identity(
            user_id=row["user_id"],
            email=row["email"],
            display_name=row["display_name"],
            active=bool(row["active"]),
            role=row["role"],
            manager_user_id=row["manager_user_id"],
        )

    @staticmethod
    def _knowledgebase(row: sqlite3.Row) -> Knowledgebase:
        return Knowledgebase(
            knowledgebase_id=row["knowledgebase_id"],
            slug=row["slug"],
            label=row["label"],
            purpose=row["purpose"],
            status=row["status"],
        )

    @staticmethod
    def _required(value: Any, name: str) -> str:
        clean = str(value or "").strip()
        if not clean:
            raise GovernanceError(f"{name}_required")
        return clean

    @classmethod
    def _email(cls, value: Any) -> str:
        clean = cls._required(value, "email").lower()
        if "@" not in clean or clean.startswith("@") or clean.endswith("@"):
            raise GovernanceError("invalid_email")
        return clean

    @classmethod
    def _slug(cls, value: Any) -> str:
        clean = cls._required(value, "slug").lower()
        if not all(character.isalnum() or character in {"-", "_"} for character in clean):
            raise GovernanceError("invalid_knowledgebase_slug")
        if len(clean) < 2 or len(clean) > 48:
            raise GovernanceError("invalid_knowledgebase_slug")
        return clean


def serialize(value: Any) -> Any:
    """Small adapter helper for FastAPI responses without leaking DB rows."""
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [serialize(item) for item in value]
    return value
