from __future__ import annotations

import calendar
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

try:
    from .portal_governance import SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import SQLiteGovernanceStore


class MaintenanceError(ValueError):
    pass


def easter_sunday(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f, g = (b + 8) // 25, (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return date(year, month, (h + l - 7 * m + 114) % 31 + 1)


def niedersachsen_holidays(year: int) -> set[date]:
    easter = easter_sunday(year)
    return {
        date(year, 1, 1), easter - timedelta(days=2), easter + timedelta(days=1),
        date(year, 5, 1), easter + timedelta(days=39), easter + timedelta(days=50),
        date(year, 10, 3), date(year, 10, 31), date(year, 12, 25), date(year, 12, 26),
    }


def is_workday(value: date) -> bool:
    return value.weekday() < 5 and value not in niedersachsen_holidays(value.year)


def workdays_until(start: date, end: date) -> int:
    if end < start:
        return -workdays_until(end, start)
    current, count = start, 0
    while current < end:
        current += timedelta(days=1)
        if is_workday(current):
            count += 1
    return count


@dataclass(frozen=True)
class OutboxMessage:
    message_id: str
    recipient: str
    subject: str
    body: str
    kind: str
    scheduled_for: str


class MaintenanceService:
    TRASH_RECOVERY_DAYS = 30
    TRASH_DELETION_DAYS = 90
    SUPERSEDED_VERSION_RETENTION_DAYS = 90
    REMINDER_STAGES = (7, 5, 1)

    def __init__(self, store: SQLiteGovernanceStore, *, today: Callable[[], date] = date.today,
                 now: Callable[[], str] | None = None, portal_public_url: str | None = None):
        self.store, self.today = store, today
        self.now = now or (lambda: datetime.now().astimezone().isoformat())
        self.portal_public_url = (
            portal_public_url
            if portal_public_url is not None
            else os.getenv("PORTAL_PUBLIC_URL", "")
        ).rstrip("/")
        self._initialize()

    def _document_url(self, document_id: str) -> str:
        path = f"/wissen/?document={document_id}"
        return f"{self.portal_public_url}{path}" if self.portal_public_url else path

    def _initialize(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS notification_outbox (
                    message_id TEXT PRIMARY KEY, recipient TEXT NOT NULL, subject TEXT NOT NULL,
                    body TEXT NOT NULL, kind TEXT NOT NULL, scheduled_for TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT, sent_at TEXT,
                    UNIQUE(recipient, kind, scheduled_for)
                );
                CREATE TABLE IF NOT EXISTS document_trash (
                    document_id TEXT PRIMARY KEY, trashed_at TEXT NOT NULL, trashed_by TEXT NOT NULL,
                    reason TEXT NOT NULL, legal_hold INTEGER NOT NULL DEFAULT 0,
                    hold_reason TEXT, review_at TEXT, physically_deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS document_trash_reads (
                    user_id TEXT NOT NULL REFERENCES portal_users(user_id),
                    document_id TEXT NOT NULL,
                    read_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, document_id)
                );
                CREATE TABLE IF NOT EXISTS document_removal_requests (
                    request_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, requested_by TEXT NOT NULL,
                    kind TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL, decided_by TEXT,
                    decision_reason TEXT, created_at TEXT NOT NULL, decided_at TEXT
                );
                CREATE TABLE IF NOT EXISTS deletion_audit (
                    document_id TEXT PRIMARY KEY, neutral_title TEXT NOT NULL, original_sha256 TEXT NOT NULL,
                    knowledgebase_ids_json TEXT NOT NULL, uploaded_at TEXT, approved_at TEXT,
                    trashed_at TEXT NOT NULL, deleted_at TEXT NOT NULL, actor_ids_json TEXT NOT NULL,
                    reason TEXT NOT NULL, legal_hold INTEGER NOT NULL
                );
                """
            )

    def enforce_retention(self) -> dict[str, int]:
        cutoffs = {
            "audit": (self.today() - timedelta(days=730)).isoformat(),
            "security": (self.today() - timedelta(days=365)).isoformat(),
            "technical": (self.today() - timedelta(days=183)).isoformat(),
        }
        removed: dict[str, int] = {}
        with self.store.connect() as db:
            removed["governance_audit"] = db.execute("DELETE FROM governance_audit WHERE occurred_at < ?", (cutoffs["audit"],)).rowcount
            removed["document_events"] = db.execute("DELETE FROM document_events WHERE created_at < ?", (cutoffs["audit"],)).rowcount
            removed["decisions"] = db.execute("DELETE FROM document_decisions WHERE created_at < ?", (cutoffs["audit"],)).rowcount
            removed["system_incidents"] = db.execute("DELETE FROM system_incidents WHERE created_at < ? AND status != 'open'", (cutoffs["security"],)).rowcount
            removed["rag_feedback"] = db.execute("DELETE FROM rag_feedback WHERE created_at < ? AND status != 'open'", (cutoffs["security"],)).rowcount
            removed["deletion_audit"] = db.execute("DELETE FROM deletion_audit WHERE deleted_at < ?", (cutoffs["audit"],)).rowcount
            removed["sent_notifications"] = db.execute("DELETE FROM notification_outbox WHERE sent_at < ? AND status='sent'", (cutoffs["technical"],)).rowcount
        return removed

    def generate_expiry_digest(self) -> list[OutboxMessage]:
        today = self.today()
        if not is_workday(today):
            return []
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT d.document_id, d.title, d.owner_user_id, v.version_id, v.valid_until,
                          p.knowledgebase_id, owner.email owner_email,
                          manager.email manager_email
                   FROM canonical_documents d
                   JOIN document_versions v ON v.version_id = d.active_version_id
                   JOIN document_publications p ON p.document_id = d.document_id AND p.status = 'active'
                   JOIN portal_users owner ON owner.user_id = d.owner_user_id
                   LEFT JOIN portal_users manager ON manager.user_id = owner.manager_user_id
                   WHERE v.status = 'active' AND v.valid_until IS NOT NULL"""
            ).fetchall()
            admin_emails = [row["email"] for row in db.execute(
                "SELECT email FROM portal_users WHERE active = 1 AND role IN ('admin','portal_admin')"
            ).fetchall()]
        grouped: dict[str, list[dict[str, Any]]] = {}
        seen: set[tuple[str, str, int]] = set()
        for row in rows:
            remaining = workdays_until(today, date.fromisoformat(row["valid_until"]))
            if remaining not in self.REMINDER_STAGES:
                continue
            recipients = [row["owner_email"]]
            if remaining <= 5 and row["manager_email"]:
                recipients.append(row["manager_email"])
            if remaining <= 1:
                recipients.extend(admin_emails)
            for recipient in dict.fromkeys(recipients):
                key = (recipient.lower(), row["document_id"], remaining)
                if key in seen:
                    continue
                seen.add(key)
                grouped.setdefault(recipient.lower(), []).append({
                    "title": row["title"], "knowledgebase": row["knowledgebase_id"],
                    "remaining": remaining, "case_url": self._document_url(row["document_id"]),
                })
        messages = []
        for recipient, items in sorted(grouped.items()):
            items.sort(key=lambda item: (item["remaining"], item["title"]))
            lines = ["Folgende Wissensdokumente laufen demnächst ab:", ""]
            for stage in self.REMINDER_STAGES[::-1]:
                stage_items = [item for item in items if item["remaining"] == stage]
                if stage_items:
                    lines.append(f"In {stage} Arbeitstag{'en' if stage != 1 else ''}:")
                    lines.extend(f"- {item['title']} · {item['knowledgebase']} · {item['case_url']}" for item in stage_items)
                    lines.append("")
            message = self._enqueue(recipient, "expiry_digest", today.isoformat(),
                                    "KAHLE-Vinci: Ablaufende Wissensdokumente", "\n".join(lines).strip())
            if message:
                messages.append(message)
        return messages

    def expire_due_versions(self) -> list[str]:
        today = self.today().isoformat()
        expired: list[str] = []
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT d.document_id, d.active_version_id FROM canonical_documents d
                   JOIN document_versions v ON v.version_id = d.active_version_id
                   WHERE v.status = 'active' AND v.valid_until < ?""", (today,),
            ).fetchall()
            for row in rows:
                db.execute("UPDATE document_versions SET status = 'expired' WHERE version_id = ?", (row["active_version_id"],))
                db.execute("UPDATE document_publications SET status = 'inactive', updated_at = ? WHERE document_id = ? AND status = 'active'", (self.now(), row["document_id"]))
                db.execute("UPDATE canonical_documents SET active_version_id = NULL, updated_at = ? WHERE document_id = ?", (self.now(), row["document_id"]))
                db.execute("UPDATE document_cases SET status = 'expired', updated_at = ? WHERE version_id = ? AND status = 'active'", (self.now(), row["active_version_id"]))
                expired.append(row["document_id"])
        return expired

    def purge_superseded_version_files(self, files_root: Path) -> list[str]:
        """Remove file payloads of safely replaced versions after the retention period.

        The version row and its audit history stay in place. This leaves a
        compact, auditable record while removing the original and RAG Markdown.
        """
        cutoff = (self.today() - timedelta(days=self.SUPERSEDED_VERSION_RETENTION_DAYS)).isoformat()
        root = files_root.resolve()
        purged: list[str] = []
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT v.version_id, v.document_id, v.superseded_at
                   FROM document_versions v
                   JOIN canonical_documents d ON d.document_id=v.document_id
                   WHERE v.status='superseded' AND v.superseded_at IS NOT NULL
                     AND substr(v.superseded_at, 1, 10) <= ?
                     AND d.active_version_id IS NOT NULL
                     AND d.active_version_id <> v.version_id
                   ORDER BY v.superseded_at, v.version_id""",
                (cutoff,),
            ).fetchall()
            for row in rows:
                document_root = (root / row["document_id"]).resolve()
                version_root = (document_root / row["version_id"]).resolve()
                if root not in document_root.parents or document_root.parent != root:
                    continue
                if version_root.parent != document_root:
                    continue
                if version_root.exists():
                    if not version_root.is_dir():
                        continue
                    shutil.rmtree(version_root)
                updated = db.execute(
                    """UPDATE document_versions SET status='purged', purged_at=?
                       WHERE version_id=? AND status='superseded'""",
                    (self.now(), row["version_id"]),
                )
                if not updated.rowcount:
                    continue
                case = db.execute(
                    "SELECT case_id FROM document_cases WHERE version_id=? ORDER BY created_at DESC LIMIT 1",
                    (row["version_id"],),
                ).fetchone()
                if case:
                    db.execute(
                        """INSERT INTO document_events
                           (case_id, actor_user_id, event_type, details_json, created_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            case["case_id"], "system", "superseded_version_purged",
                            json.dumps({
                                "retention_days": self.SUPERSEDED_VERSION_RETENTION_DAYS,
                                "superseded_at": row["superseded_at"],
                            }, ensure_ascii=False, sort_keys=True),
                            self.now(),
                        ),
                    )
                purged.append(row["version_id"])
        return purged

    def process_pending_approvals(self) -> dict[str, list[str]]:
        """Apply the 2/4/6-workday reminder and escalation policy."""
        today = self.today()
        if not is_workday(today):
            return {"reminders": [], "delegated": [], "escalated": [], "admin_fallback": []}
        reminders: list[str] = []
        delegated: list[str] = []
        escalated: list[str] = []
        admin_fallback: list[str] = []
        with self.store.connect() as db:
            cases = db.execute(
                """SELECT c.case_id, c.created_at, c.manager_user_id, c.requires_admin,
                          c.version_id, c.uploaded_by_user_id, d.owner_user_id,
                          manager.email manager_email
                   FROM document_cases c
                   JOIN canonical_documents d ON d.document_id=c.document_id
                   LEFT JOIN portal_users manager ON manager.user_id=c.manager_user_id
                   WHERE c.status='pending_manager_approval'"""
            ).fetchall()
            admins = [row["email"] for row in db.execute(
                "SELECT email FROM portal_users WHERE active=1 AND role IN ('admin','portal_admin')"
            ).fetchall()]
            for case in cases:
                age = workdays_until(date.fromisoformat(case["created_at"][:10]), today)
                absent = bool(db.execute(
                    "SELECT 1 FROM manager_absences WHERE manager_user_id=? AND absent_from<=? AND absent_until>=?",
                    (case["manager_user_id"], today.isoformat(), today.isoformat()),
                ).fetchone())
                delegates = [row["email"] for row in db.execute(
                    """SELECT user.email FROM manager_delegates md
                       JOIN portal_users user ON user.user_id=md.delegate_user_id
                         AND user.active=1 AND user.role IN ('manager','admin','portal_admin')
                       WHERE md.manager_user_id=? AND (md.valid_from IS NULL OR md.valid_from<=?)
                         AND (md.valid_until IS NULL OR md.valid_until>=?)
                         AND user.user_id<>? AND user.user_id<>?
                         AND NOT EXISTS (
                           SELECT 1 FROM manager_absences absence
                           WHERE absence.manager_user_id=user.user_id
                             AND absence.absent_from<=? AND absence.absent_until>=?
                         )""",
                    (case["manager_user_id"], today.isoformat(), today.isoformat(),
                     case["uploaded_by_user_id"], case["owner_user_id"],
                     today.isoformat(), today.isoformat()),
                ).fetchall()]
                if age == 2 and case["manager_email"]:
                    message = self._enqueue_db(db, case["manager_email"], f"approval_reminder:{case['case_id']}",
                                            today.isoformat(), "KAHLE-Vinci: Freigabe wartet",
                                            f"Der Vorgang {case['case_id']} wartet seit zwei Arbeitstagen. /wissen/?case={case['case_id']}")
                    if message: reminders.append(message.message_id)
                delegate_due = absent or age >= 4
                if delegate_due and not delegates:
                    db.execute(
                        "UPDATE document_cases SET status='pending_admin_approval', requires_admin=1, updated_at=? WHERE case_id=?",
                        (self.now(), case["case_id"]),
                    )
                    db.execute(
                        "UPDATE document_versions SET status='pending_admin_approval' WHERE version_id=?",
                        (case["version_id"],),
                    )
                    for recipient in admins:
                        message = self._enqueue_db(
                            db, recipient, f"approval_admin_fallback:{case['case_id']}",
                            today.isoformat(), "KAHLE-Vinci: Vertretung nicht verfügbar",
                            f"Für den Vorgang {case['case_id']} ist keine verfügbare Vertretung vorhanden. /wissen/?case={case['case_id']}",
                        )
                        if message:
                            admin_fallback.append(message.message_id)
                    continue
                if delegate_due:
                    for recipient in delegates:
                        message = self._enqueue_db(db, recipient, f"approval_delegated:{case['case_id']}",
                                                today.isoformat(), "KAHLE-Vinci: Vertretungsfall",
                                                f"Der Vorgang {case['case_id']} ist jetzt auch dir zugeordnet. /wissen/?case={case['case_id']}")
                        if message: delegated.append(message.message_id)
                if age >= 6 and not case["requires_admin"]:
                    for recipient in admins:
                        message = self._enqueue_db(db, recipient, f"approval_escalated:{case['case_id']}",
                                                today.isoformat(), "KAHLE-Vinci: Freigabe eskaliert",
                                                f"Der Vorgang {case['case_id']} wartet seit sechs Arbeitstagen. /wissen/?case={case['case_id']}")
                        if message: escalated.append(message.message_id)
                    db.execute("UPDATE document_cases SET requires_admin=1, updated_at=? WHERE case_id=?",
                               (self.now(), case["case_id"]))
        return {"reminders": reminders, "delegated": delegated, "escalated": escalated,
                "admin_fallback": admin_fallback}

    def request_removal(self, document_id: str, actor_user_id: str, kind: str, reason: str) -> str:
        if kind not in {"deactivate", "delete"} or len(reason.strip()) < 3:
            raise MaintenanceError("removal_reason_required")
        request_id = hashlib.sha256(f"{document_id}|{actor_user_id}|{self.now()}".encode()).hexdigest()[:32]
        with self.store.connect() as db:
            document = db.execute("SELECT owner_user_id FROM canonical_documents WHERE document_id = ?", (document_id,)).fetchone()
            actor = db.execute("SELECT role FROM portal_users WHERE user_id = ? AND active = 1", (actor_user_id,)).fetchone()
            if not document or not actor:
                raise MaintenanceError("removal_not_allowed")
            is_manager = bool(db.execute("SELECT 1 FROM portal_users WHERE user_id = ? AND manager_user_id = ?", (document["owner_user_id"], actor_user_id)).fetchone())
            if actor_user_id != document["owner_user_id"] and not is_manager and actor["role"] not in {"admin", "portal_admin"}:
                raise MaintenanceError("removal_not_allowed")
            status = "approved" if actor["role"] in {"admin", "portal_admin"} else "pending"
            db.execute("INSERT INTO document_removal_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (request_id, document_id, actor_user_id, kind, reason.strip(), status,
                        actor_user_id if status == "approved" else None, reason.strip() if status == "approved" else None,
                        self.now(), self.now() if status == "approved" else None))
        if status == "approved":
            self.move_to_trash(document_id, actor_user_id, reason)
        return request_id

    def decide_removal(self, request_id: str, actor_user_id: str, approve: bool, reason: str) -> None:
        if len(reason.strip()) < 3:
            raise MaintenanceError("decision_reason_required")
        with self.store.connect() as db:
            actor = db.execute("SELECT role FROM portal_users WHERE user_id = ? AND active = 1", (actor_user_id,)).fetchone()
            request = db.execute("SELECT * FROM document_removal_requests WHERE request_id = ?", (request_id,)).fetchone()
            if not actor or actor["role"] not in {"admin", "portal_admin"}: raise MaintenanceError("admin_required")
            if not request or request["status"] != "pending": raise MaintenanceError("removal_request_not_pending")
            db.execute("UPDATE document_removal_requests SET status=?, decided_by=?, decision_reason=?, decided_at=? WHERE request_id=?",
                       ("approved" if approve else "rejected", actor_user_id, reason.strip(), self.now(), request_id))
        if approve:
            self.move_to_trash(request["document_id"], actor_user_id, reason)

    def list_removals(self, actor_user_id: str | None = None) -> dict[str, Any]:
        # Dokumenttitel mitliefern: Mit einer blossen UUID kann ein Admin nicht
        # entscheiden, ob er etwas wiederherstellen oder endgueltig loeschen will.
        with self.store.connect() as db:
            requests = [dict(row) for row in db.execute(
                """SELECT r.*, d.title FROM document_removal_requests r
                   LEFT JOIN canonical_documents d ON d.document_id = r.document_id
                   ORDER BY r.created_at DESC"""
            ).fetchall()]
            trash = [dict(row) for row in db.execute(
                """SELECT t.*, d.title FROM document_trash t
                   LEFT JOIN canonical_documents d ON d.document_id = t.document_id
                   WHERE t.physically_deleted_at IS NULL ORDER BY t.trashed_at"""
            ).fetchall()]
            unread_count = 0
            if actor_user_id:
                unread_count = db.execute(
                    """SELECT COUNT(*) AS count FROM document_trash t
                       WHERE t.physically_deleted_at IS NULL AND NOT EXISTS (
                         SELECT 1 FROM document_trash_reads r
                         WHERE r.user_id=? AND r.document_id=t.document_id
                       )""",
                    (actor_user_id,),
                ).fetchone()["count"]
        for item in trash:
            eligible_on = date.fromisoformat(item["trashed_at"]) + timedelta(days=self.TRASH_RECOVERY_DAYS)
            item["delete_eligible_on"] = eligible_on.isoformat()
            item["can_delete"] = self.today() >= eligible_on and not bool(item["legal_hold"])
        return {"requests": requests, "trash": trash, "unread_count": int(unread_count)}

    def mark_trash_read(self, actor_user_id: str) -> None:
        with self.store.connect() as db:
            actor = db.execute(
                "SELECT role FROM portal_users WHERE user_id=? AND active=1", (actor_user_id,),
            ).fetchone()
            if not actor or actor["role"] not in {"admin", "portal_admin"}:
                raise MaintenanceError("admin_required")
            db.execute(
                """INSERT OR REPLACE INTO document_trash_reads(user_id,document_id,read_at)
                   SELECT ?,document_id,? FROM document_trash
                   WHERE physically_deleted_at IS NULL""",
                (actor_user_id, self.now()),
            )

    def restore_from_trash(self, document_id: str, actor_user_id: str, reason: str) -> None:
        if len(reason.strip()) < 3: raise MaintenanceError("restore_reason_required")
        with self.store.connect() as db:
            actor = db.execute("SELECT role FROM portal_users WHERE user_id=? AND active=1", (actor_user_id,)).fetchone()
            trash = db.execute("SELECT * FROM document_trash WHERE document_id=? AND physically_deleted_at IS NULL", (document_id,)).fetchone()
            if not actor or actor["role"] not in {"admin", "portal_admin"}: raise MaintenanceError("admin_required")
            if not trash: raise MaintenanceError("document_not_in_trash")
            version = db.execute("SELECT * FROM document_versions WHERE document_id=? ORDER BY COALESCE(activated_at, created_at) DESC LIMIT 1", (document_id,)).fetchone()
            if not version or not version["valid_until"] or date.fromisoformat(version["valid_until"]) < self.today():
                raise MaintenanceError("restore_requires_new_approval")
            db.execute("UPDATE document_versions SET status='active' WHERE version_id=?", (version["version_id"],))
            db.execute("UPDATE canonical_documents SET active_version_id=?, updated_at=? WHERE document_id=?", (version["version_id"], self.now(), document_id))
            db.execute("UPDATE document_publications SET status='active', updated_at=? WHERE document_id=?", (self.now(), document_id))
            db.execute("DELETE FROM document_trash WHERE document_id=?", (document_id,))
            db.execute("INSERT INTO document_events(case_id, actor_user_id, event_type, details_json, created_at) SELECT case_id, ?, 'restored_from_trash', ?, ? FROM document_cases WHERE document_id=? ORDER BY created_at DESC LIMIT 1",
                       (actor_user_id, json.dumps({"reason": reason.strip()}), self.now(), document_id))

    def set_legal_hold(self, document_id: str, actor_user_id: str, enabled: bool, reason: str, review_at: str | None) -> None:
        if len(reason.strip()) < 3 or (enabled and not review_at): raise MaintenanceError("legal_hold_reason_and_review_required")
        with self.store.connect() as db:
            actor = db.execute("SELECT role FROM portal_users WHERE user_id=? AND active=1", (actor_user_id,)).fetchone()
            if not actor or actor["role"] not in {"admin", "portal_admin"}: raise MaintenanceError("admin_required")
            cursor = db.execute("UPDATE document_trash SET legal_hold=?, hold_reason=?, review_at=? WHERE document_id=? AND physically_deleted_at IS NULL",
                                (int(enabled), reason.strip(), review_at, document_id))
            if not cursor.rowcount: raise MaintenanceError("document_not_in_trash")

    def move_to_trash(self, document_id: str, actor_user_id: str, reason: str) -> None:
        if len(reason.strip()) < 3:
            raise MaintenanceError("trash_reason_required")
        with self.store.connect() as db:
            document = db.execute("SELECT active_version_id FROM canonical_documents WHERE document_id = ?", (document_id,)).fetchone()
            if not document:
                raise MaintenanceError("unknown_document")
            db.execute("UPDATE document_versions SET status = 'trash' WHERE document_id = ? AND status != 'deleted'", (document_id,))
            db.execute("UPDATE document_publications SET status = 'inactive', updated_at = ? WHERE document_id = ?", (self.now(), document_id))
            db.execute("UPDATE canonical_documents SET active_version_id = NULL, updated_at = ? WHERE document_id = ?", (self.now(), document_id))
            db.execute(
                """INSERT INTO document_trash(document_id, trashed_at, trashed_by, reason)
                   VALUES (?, ?, ?, ?) ON CONFLICT(document_id) DO NOTHING""",
                (document_id, self.today().isoformat(), actor_user_id, reason.strip()),
            )
            db.execute(
                "INSERT INTO document_events(case_id, actor_user_id, event_type, details_json, created_at) "
                "SELECT case_id, ?, 'moved_to_trash', ?, ? FROM document_cases "
                "WHERE document_id=? ORDER BY created_at DESC LIMIT 1",
                (actor_user_id, json.dumps({"reason": reason.strip()}), self.now(), document_id),
            )

    def process_trash(self, file_root: Path | None = None) -> dict[str, list[str]]:
        today = self.today()
        reminders, deleted = [], []
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT trash.*, document.title FROM document_trash trash
                   LEFT JOIN canonical_documents document ON document.document_id = trash.document_id
                   WHERE trash.physically_deleted_at IS NULL"""
            ).fetchall()
            admins = [row["email"] for row in db.execute(
                "SELECT email FROM portal_users WHERE active = 1 AND role IN ('admin','portal_admin')"
            ).fetchall()]
            deletion_candidates: list[dict[str, str]] = []
            for row in rows:
                age = (today - date.fromisoformat(row["trashed_at"])).days
                if row["legal_hold"]:
                    continue
                if age >= self.TRASH_DELETION_DAYS:
                    self._physically_delete(db, row, file_root)
                    deleted.append(row["document_id"])
                    continue
                deletion_date = date.fromisoformat(row["trashed_at"]) + timedelta(
                    days=self.TRASH_DELETION_DAYS,
                )
                if is_workday(today) and workdays_until(today, deletion_date) == 4:
                    deletion_candidates.append({
                        "document_id": row["document_id"],
                        "title": row["title"] or "Dokument ohne Titel",
                    })
        if deletion_candidates:
            lines = [
                "Folgende Dokumente werden in vier Arbeitstagen endgültig gelöscht:",
                "",
            ]
            lines.extend(
                f"- {item['title']} · {self._document_url(item['document_id'])}"
                for item in sorted(deletion_candidates, key=lambda item: item["title"])
            )
            body = "\n".join(lines)
            for recipient in admins:
                message = self._enqueue(
                    recipient,
                    "trash_deletion_digest",
                    today.isoformat(),
                    "KAHLE-Vinci: Endgültige Löschung aus dem Papierkorb",
                    body,
                )
                if message:
                    reminders.append(message.message_id)
        return {"reminders": reminders, "deleted": deleted}

    def process_migration_deadlines(self) -> list[str]:
        """Deactivate unresolved legacy inventory after its 30-workday transition."""
        with self.store.connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_inventory'").fetchone():
                return []
            rows = db.execute("""SELECT path FROM migration_inventory
                                 WHERE transition_status='pending' AND transition_deadline<=?
                                 AND status NOT IN ('staged','quarantine','transition_expired','excluded')""",
                              (self.today().isoformat(),)).fetchall()
            paths = [row["path"] for row in rows]
            if paths:
                placeholders = ",".join("?" for _ in paths)
                db.execute(f"""UPDATE migration_inventory SET status='transition_expired',
                              transition_status='expired',updated_at=? WHERE path IN ({placeholders})""",
                           (self.now(), *paths))
        return paths

    def _physically_delete(self, db, trash_row, file_root: Path | None) -> None:
        document_id = trash_row["document_id"]
        # Der Analysekorpus verweist auf Versionen. Bleibt der Eintrag nach
        # der physischen Loeschung stehen, meldet er weiter Aehnlichkeit
        # fuer ein Dokument, das es nicht mehr gibt. Die Tabelle gehoert einem
        # anderen Modul und fehlt in Aufbauten ohne Analysekorpus.
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='global_analysis_corpus'"
        ).fetchone():
            db.execute(
                "DELETE FROM global_analysis_corpus WHERE document_id = ?", (document_id,),
            )
        document = db.execute("SELECT title, created_at FROM canonical_documents WHERE document_id = ?", (document_id,)).fetchone()
        versions = db.execute("SELECT original_sha256, created_at, activated_at FROM document_versions WHERE document_id = ? ORDER BY created_at", (document_id,)).fetchall()
        kbs = [row["knowledgebase_id"] for row in db.execute("SELECT knowledgebase_id FROM document_publications WHERE document_id = ?", (document_id,)).fetchall()]
        actors = [row["actor_user_id"] for row in db.execute("SELECT DISTINCT actor_user_id FROM document_events WHERE case_id IN (SELECT case_id FROM document_cases WHERE document_id = ?)", (document_id,)).fetchall()]
        db.execute(
            """INSERT OR REPLACE INTO deletion_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (document_id, (document["title"] if document else "Gelöschtes Dokument")[:120],
             versions[-1]["original_sha256"] if versions else "", json.dumps(kbs),
             document["created_at"] if document else None, versions[-1]["activated_at"] if versions else None,
             trash_row["trashed_at"], self.now(), json.dumps(actors), trash_row["reason"], int(trash_row["legal_hold"])),
        )
        db.execute("DELETE FROM document_publications WHERE document_id = ?", (document_id,))
        db.execute("DELETE FROM document_decisions WHERE case_id IN (SELECT case_id FROM document_cases WHERE document_id = ?)", (document_id,))
        db.execute("DELETE FROM document_events WHERE case_id IN (SELECT case_id FROM document_cases WHERE document_id = ?)", (document_id,))
        db.execute("DELETE FROM document_cases WHERE document_id = ?", (document_id,))
        db.execute("DELETE FROM document_versions WHERE document_id = ?", (document_id,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_authority_relations'").fetchone():
            db.execute("DELETE FROM document_authority_relations WHERE source_document_id=? OR target_document_id=?", (document_id, document_id))
        db.execute("DELETE FROM document_metadata WHERE document_id = ?", (document_id,))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='owner_reassignment_tasks'").fetchone():
            db.execute("DELETE FROM owner_reassignment_tasks WHERE document_id = ?", (document_id,))
        db.execute("DELETE FROM canonical_documents WHERE document_id = ?", (document_id,))
        db.execute("UPDATE document_trash SET physically_deleted_at = ? WHERE document_id = ?", (self.now(), document_id))
        if file_root:
            target = (file_root / document_id).resolve()
            try:
                target.relative_to(file_root.resolve())
            except ValueError:
                return
            if target.exists():
                import shutil
                shutil.rmtree(target)

    def _enqueue_db(self, db, recipient: str, kind: str, scheduled_for: str, subject: str, body: str) -> OutboxMessage | None:
        message_id = hashlib.sha256(f"{recipient}|{kind}|{scheduled_for}".encode()).hexdigest()[:32]
        cursor = db.execute(
            """INSERT OR IGNORE INTO notification_outbox
               (message_id, recipient, subject, body, kind, scheduled_for)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (message_id, recipient, subject, body, kind, scheduled_for),
        )
        return OutboxMessage(message_id, recipient, subject, body, kind, scheduled_for) if cursor.rowcount else None

    def _enqueue(self, recipient: str, kind: str, scheduled_for: str, subject: str, body: str) -> OutboxMessage | None:
        with self.store.connect() as db:
            return self._enqueue_db(db, recipient, kind, scheduled_for, subject, body)

    def enqueue_notification(
        self, recipient: str, kind: str, subject: str, body: str, *, dedupe_key: str,
    ) -> OutboxMessage | None:
        return self._enqueue(recipient.lower(), kind, dedupe_key, subject, body)

    def mark_sent(self, message_id: str) -> None:
        with self.store.connect() as db:
            db.execute(
                "UPDATE notification_outbox SET status = 'sent', sent_at = ?, attempts = attempts + 1, last_error = NULL WHERE message_id = ?",
                (self.now(), message_id),
            )

    def mark_failed(self, message_id: str, error: str) -> None:
        with self.store.connect() as db:
            db.execute(
                "UPDATE notification_outbox SET attempts = attempts + 1, last_error = ? WHERE message_id = ?",
                (error[:500], message_id),
            )

    def pending_messages(self, limit: int = 100) -> list[OutboxMessage]:
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM notification_outbox WHERE status = 'pending' ORDER BY scheduled_for, message_id LIMIT ?", (limit,)).fetchall()
        return [OutboxMessage(row["message_id"], row["recipient"], row["subject"], row["body"], row["kind"], row["scheduled_for"]) for row in rows]


    def delete_now(self, document_id: str, actor_user_id: str, reason: str,
                   file_root: Path | None = None) -> None:
        """
        Manuelle physische Loeschung nach der 30-taegigen Wiederherstellungsfrist.

        Admins und Portal-Admins duerfen den Auftrag ab Tag 30 ausfuehren. Bis
        dahin bleibt das Dokument zwingend wiederherstellbar. Ein Legal Hold
        setzt auch danach jede Loeschung aus.
        """
        if len(reason.strip()) < 3:
            raise MaintenanceError("deletion_reason_required")
        with self.store.connect() as db:
            actor = db.execute(
                "SELECT role FROM portal_users WHERE user_id=? AND active=1", (actor_user_id,)
            ).fetchone()
            if not actor or actor["role"] not in {"admin", "portal_admin"}:
                raise MaintenanceError("admin_required")
            row = db.execute(
                "SELECT * FROM document_trash WHERE document_id=? AND physically_deleted_at IS NULL",
                (document_id,),
            ).fetchone()
            if not row:
                raise MaintenanceError("trash_entry_not_found")
            if row["legal_hold"]:
                raise MaintenanceError("legal_hold_blocks_deletion")
            eligible_on = date.fromisoformat(row["trashed_at"]) + timedelta(days=self.TRASH_RECOVERY_DAYS)
            if self.today() < eligible_on:
                raise MaintenanceError("trash_recovery_period_active")
            self._physically_delete(db, row, file_root)
