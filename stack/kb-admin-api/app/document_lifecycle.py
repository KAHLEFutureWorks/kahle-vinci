from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Literal

try:
    from .portal_governance import GovernanceError, PortalGovernance, SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import GovernanceError, PortalGovernance, SQLiteGovernanceStore


Confidentiality = Literal["internal", "restricted", "confidential"]
UserAction = Literal["create", "replace", "publish_existing", "discard"]
Decision = Literal["approve", "reject", "escalate"]


class LifecycleError(ValueError):
    """Stable document workflow error exposed by the module interface."""


@dataclass(frozen=True)
class Submission:
    case_id: str
    document_id: str
    version_id: str
    owner_user_id: str
    uploaded_by_user_id: str
    target_knowledgebase_id: str
    title: str
    original_filename: str
    original_sha256: str
    valid_workdays: int
    confidentiality: Confidentiality
    status: str
    requested_action: str | None
    manager_user_id: str | None
    requires_admin: bool


@dataclass(frozen=True)
class Analysis:
    exact_duplicate_document_id: str | None = None
    normalized_duplicate_document_id: str | None = None
    same_kb_similarity: str = "none"
    cross_kb_matches: tuple[str, ...] = ()
    contradiction_document_ids: tuple[str, ...] = ()
    version_candidate_document_ids: tuple[str, ...] = ()
    prompt_injection_risk: str = "none"
    malware_safe: bool = True
    conversion_quality: str = "good"
    notes: tuple[str, ...] = ()



def _is_workday(value: date, holidays: set[date] | None = None) -> bool:
    if value.weekday() >= 5:
        return False
    if holidays is not None:
        return value not in holidays
    try:
        from .maintenance import niedersachsen_holidays
    except ImportError:  # pragma: no cover
        from maintenance import niedersachsen_holidays
    return value not in niedersachsen_holidays(value.year)


def add_workdays(start: date, workdays: int, holidays: set[date] | None = None) -> date:
    if workdays < 1 or workdays > 60:
        raise LifecycleError("valid_workdays_out_of_range")
    current = start
    remaining = workdays
    while remaining:
        current += timedelta(days=1)
        if _is_workday(current, holidays):
            remaining -= 1
    return current


def workdays_until(start: date, target: date, holidays: set[date] | None = None) -> int:
    """
    Zahl der Arbeitstage zwischen ``start`` (ausschliesslich) und ``target``
    (einschliesslich).

    Umkehrung von :func:`add_workdays` fuer die vom PRD 17.1 zugelassene Auswahl
    eines geprueften Datums. Faellt ``target`` auf ein Wochenende oder einen
    Feiertag, ergibt sich die Zahl der Arbeitstage bis zum davorliegenden
    Arbeitstag; die Gueltigkeit wird dadurch kuerzer, niemals laenger.
    """
    if target <= start:
        raise LifecycleError("valid_until_not_in_future")
    workdays = 0
    current = start
    while current < target:
        current += timedelta(days=1)
        if _is_workday(current, holidays):
            workdays += 1
    if workdays < 1:
        raise LifecycleError("valid_until_has_no_workday")
    if workdays > 60:
        raise LifecycleError("valid_workdays_out_of_range")
    return workdays


class DocumentLifecycle:
    """
    Deep module owning document workflow state and approval invariants.

    File storage, conversion, scanners, mail and indexing remain adapters. They
    report outcomes through this interface; only this module decides whether a
    version may progress toward activation.
    """

    def __init__(
        self,
        store: SQLiteGovernanceStore,
        governance: PortalGovernance,
        *,
        today: Callable[[], date] = date.today,
        now: Callable[[], str] = lambda: datetime.now().astimezone().isoformat(),
        identifier: Callable[[], str] = lambda: str(uuid.uuid4()),
        holidays: set[date] | None = None,
    ):
        self.store = store
        self.governance = governance
        self.today = today
        self.now = now
        self.identifier = identifier
        self.holidays = set(holidays) if holidays is not None else None
        self._initialize()

    def _initialize(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS canonical_documents (
                    document_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL REFERENCES portal_users(user_id),
                    confidentiality TEXT NOT NULL
                        CHECK (confidentiality IN ('internal','restricted','confidential')),
                    active_version_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS document_metadata (
                    document_id TEXT PRIMARY KEY REFERENCES canonical_documents(document_id),
                    authority_type TEXT NOT NULL DEFAULT 'information_or_training',
                    authority_level INTEGER NOT NULL DEFAULT 6 CHECK(authority_level BETWEEN 1 AND 6),
                    scope_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS document_versions (
                    version_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES canonical_documents(document_id),
                    previous_version_id TEXT REFERENCES document_versions(version_id),
                    original_filename TEXT NOT NULL,
                    original_file_id TEXT NOT NULL,
                    original_sha256 TEXT NOT NULL,
                    normalized_sha256 TEXT,
                    markdown_sha256 TEXT,
                    valid_workdays INTEGER NOT NULL CHECK (valid_workdays BETWEEN 1 AND 60),
                    valid_from TEXT,
                    valid_until TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    activated_at TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_active_binary_duplicate
                    ON document_versions(original_sha256)
                    WHERE status = 'active';
                CREATE INDEX IF NOT EXISTS idx_normalized_duplicate
                    ON document_versions(normalized_sha256, status);

                CREATE TABLE IF NOT EXISTS document_publications (
                    document_id TEXT NOT NULL REFERENCES canonical_documents(document_id),
                    knowledgebase_id TEXT NOT NULL REFERENCES knowledgebases(knowledgebase_id),
                    status TEXT NOT NULL CHECK (status IN ('pending','active','inactive')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (document_id, knowledgebase_id)
                );

                CREATE TABLE IF NOT EXISTS document_cases (
                    case_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES canonical_documents(document_id),
                    version_id TEXT NOT NULL REFERENCES document_versions(version_id),
                    uploaded_by_user_id TEXT NOT NULL REFERENCES portal_users(user_id),
                    target_knowledgebase_id TEXT NOT NULL REFERENCES knowledgebases(knowledgebase_id),
                    manager_user_id TEXT REFERENCES portal_users(user_id),
                    status TEXT NOT NULL,
                    requested_action TEXT,
                    requires_admin INTEGER NOT NULL DEFAULT 0,
                    analysis_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS document_decisions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL REFERENCES document_cases(case_id),
                    actor_user_id TEXT NOT NULL REFERENCES portal_users(user_id),
                    actor_role TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS document_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL REFERENCES document_cases(case_id),
                    actor_user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def submit(
        self,
        *,
        uploaded_by_user_id: str,
        owner_user_id: str,
        target_knowledgebase_id: str,
        title: str,
        original_filename: str,
        original_file_id: str,
        original_sha256: str,
        valid_workdays: int,
        confidentiality: Confidentiality,
        document_id: str | None = None,
        version_id: str | None = None,
        case_id: str | None = None,
    ) -> Submission:
        self.governance.require_access(uploaded_by_user_id, target_knowledgebase_id, "upload")
        owner = self.governance.identity(owner_user_id)
        if not owner.active:
            raise LifecycleError("owner_inactive")
        if confidentiality not in {"internal", "restricted", "confidential"}:
            raise LifecycleError("invalid_confidentiality")
        if valid_workdays < 1 or valid_workdays > 60:
            raise LifecycleError("valid_workdays_out_of_range")
        title = self._required(title, "title")
        filename = self._required(original_filename, "original_filename")
        file_id = self._required(original_file_id, "original_file_id")
        sha256 = self._sha256(original_sha256)
        stamp = self.now()
        document_id = document_id or self.identifier()
        version_id = version_id or self.identifier()
        case_id = case_id or self.identifier()
        with self.store.connect() as db:
            existing_document = db.execute(
                "SELECT * FROM canonical_documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            previous_version_id = existing_document["active_version_id"] if existing_document else None
            if existing_document and existing_document["owner_user_id"] != owner_user_id:
                raise LifecycleError("document_owner_mismatch")
            if not existing_document:
                db.execute(
                    """
                    INSERT INTO canonical_documents (
                        document_id, title, owner_user_id, confidentiality, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (document_id, title, owner_user_id, confidentiality, stamp, stamp),
                )
            db.execute(
                """INSERT OR IGNORE INTO document_metadata
                   (document_id, authority_type, authority_level, scope_json)
                   VALUES (?, 'information_or_training', 6, ?)""",
                (document_id, json.dumps({"knowledgebase_ids": [target_knowledgebase_id]}, sort_keys=True)),
            )
            db.execute(
                """
                INSERT INTO document_versions (
                    version_id, document_id, previous_version_id, original_filename,
                    original_file_id, original_sha256, valid_workdays, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'quarantine', ?)
                """,
                (
                    version_id,
                    document_id,
                    previous_version_id,
                    filename,
                    file_id,
                    sha256,
                    valid_workdays,
                    stamp,
                ),
            )
            db.execute(
                """
                INSERT INTO document_publications (
                    document_id, knowledgebase_id, status, created_at, updated_at
                ) VALUES (?, ?, 'pending', ?, ?)
                ON CONFLICT(document_id, knowledgebase_id) DO UPDATE SET
                    status = 'pending', updated_at = excluded.updated_at
                """,
                (document_id, target_knowledgebase_id, stamp, stamp),
            )
            db.execute(
                """
                INSERT INTO document_cases (
                    case_id, document_id, version_id, uploaded_by_user_id,
                    target_knowledgebase_id, manager_user_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'quarantine', ?, ?)
                """,
                (
                    case_id,
                    document_id,
                    version_id,
                    uploaded_by_user_id,
                    target_knowledgebase_id,
                    owner.manager_user_id,
                    stamp,
                    stamp,
                ),
            )
            self._event(db, case_id, uploaded_by_user_id, "submitted", {"owner_user_id": owner_user_id})
        return self.submission(case_id)

    def apply_automatic_confidentiality(
        self, *, case_id: str, level: Confidentiality, reason: str,
        signals: tuple[str, ...] = (), actor_user_id: str = "classifier",
    ) -> Submission:
        case = self.submission(case_id)
        ranks = {"internal": 0, "restricted": 1, "confidential": 2}
        if level not in ranks:
            raise LifecycleError("invalid_confidentiality")
        with self.store.connect() as db:
            current = db.execute(
                "SELECT confidentiality FROM canonical_documents WHERE document_id=?",
                (case.document_id,),
            ).fetchone()["confidentiality"]
            effective = level if ranks[level] > ranks[current] else current
            db.execute(
                "UPDATE canonical_documents SET confidentiality=?, updated_at=? WHERE document_id=?",
                (effective, self.now(), case.document_id),
            )
            self._event(db, case_id, actor_user_id, "confidentiality_classified", {
                "requested": current, "suggested": level, "effective": effective,
                "reason": reason, "signals": list(signals),
            })
        return self.submission(case_id)

    def record_analysis(
        self,
        *,
        case_id: str,
        normalized_sha256: str,
        markdown_sha256: str,
        analysis: Analysis,
        actor_user_id: str = "system",
    ) -> Submission:
        case = self.submission(case_id)
        if case.status not in {"quarantine", "processing", "needs_correction"}:
            raise LifecycleError("analysis_not_allowed")
        if not analysis.malware_safe:
            next_status = "security_blocked"
        elif analysis.prompt_injection_risk in {"medium", "high", "critical"}:
            next_status = "pending_admin_approval"
        elif analysis.conversion_quality == "failed":
            next_status = "needs_correction"
        elif analysis.exact_duplicate_document_id or analysis.normalized_duplicate_document_id:
            next_status = "duplicate_blocked"
        else:
            next_status = "pending_employee_decision"
        requires_admin = bool(
            analysis.cross_kb_matches
            or analysis.contradiction_document_ids
            or analysis.prompt_injection_risk in {"medium", "high", "critical"}
            or analysis.conversion_quality == "low"
        )
        payload = {
            "exact_duplicate_document_id": analysis.exact_duplicate_document_id,
            "normalized_duplicate_document_id": analysis.normalized_duplicate_document_id,
            "same_kb_similarity": analysis.same_kb_similarity,
            "cross_kb_matches": list(analysis.cross_kb_matches),
            "contradiction_document_ids": list(analysis.contradiction_document_ids),
            "version_candidate_document_ids": list(analysis.version_candidate_document_ids),
            "prompt_injection_risk": analysis.prompt_injection_risk,
            "malware_safe": analysis.malware_safe,
            "conversion_quality": analysis.conversion_quality,
            "notes": list(analysis.notes),
        }
        with self.store.connect() as db:
            db.execute(
                """
                UPDATE document_versions
                SET normalized_sha256 = ?, markdown_sha256 = ?, status = ?
                WHERE version_id = ?
                """,
                (self._sha256(normalized_sha256), self._sha256(markdown_sha256), next_status, case.version_id),
            )
            db.execute(
                """
                UPDATE document_cases
                SET status = ?, requires_admin = ?, analysis_json = ?, updated_at = ?
                WHERE case_id = ?
                """,
                (next_status, int(requires_admin), json.dumps(payload, sort_keys=True), self.now(), case_id),
            )
            self._event(db, case_id, actor_user_id, "analysis_recorded", {"status": next_status, **payload})
        return self.submission(case_id)

    def bind_replacement(self, *, case_id: str, target_document_id: str,
                         actor_user_id: str) -> Submission:
        case = self.submission(case_id)
        if actor_user_id != case.uploaded_by_user_id or case.status != "pending_employee_decision":
            raise LifecycleError("replacement_binding_not_allowed")
        with self.store.connect() as db:
            row = db.execute("SELECT analysis_json FROM document_cases WHERE case_id=?", (case_id,)).fetchone()
            analysis = json.loads(row["analysis_json"] or "{}")
            if target_document_id not in analysis.get("version_candidate_document_ids", []):
                raise LifecycleError("replacement_target_not_analyzed")
            target = db.execute(
                """SELECT d.active_version_id,u.manager_user_id FROM canonical_documents d
                   JOIN portal_users u ON u.user_id=d.owner_user_id
                   JOIN document_versions v ON v.version_id=d.active_version_id AND v.status='active'
                   WHERE d.document_id=?""", (target_document_id,),
            ).fetchone()
            if not target or target_document_id == case.document_id:
                raise LifecycleError("replacement_target_not_active")
            existing_publication = db.execute(
                "SELECT status FROM document_publications WHERE document_id=? AND knowledgebase_id=?",
                (target_document_id, case.target_knowledgebase_id),
            ).fetchone()
            db.execute("DELETE FROM document_publications WHERE document_id=?", (case.document_id,))
            if not existing_publication:
                db.execute(
                    "INSERT INTO document_publications VALUES (?,?,'pending',?,?)",
                    (target_document_id, case.target_knowledgebase_id, self.now(), self.now()),
                )
            db.execute(
                "UPDATE document_versions SET document_id=?,previous_version_id=?,original_file_id=? WHERE version_id=?",
                (target_document_id, target["active_version_id"], f"portal://documents/{target_document_id}", case.version_id),
            )
            db.execute(
                "UPDATE document_cases SET document_id=?,manager_user_id=?,updated_at=? WHERE case_id=?",
                (target_document_id, target["manager_user_id"], self.now(), case_id),
            )
            db.execute("DELETE FROM document_metadata WHERE document_id=?", (case.document_id,))
            db.execute("DELETE FROM canonical_documents WHERE document_id=?", (case.document_id,))
            self._event(db, case_id, actor_user_id, "replacement_target_bound", {
                "draft_document_id": case.document_id, "target_document_id": target_document_id,
                "previous_version_id": target["active_version_id"],
            })
        return self.submission(case_id)

    def choose_action(
        self, *, case_id: str, actor_user_id: str, action: UserAction
    ) -> Submission:
        case = self.submission(case_id)
        if actor_user_id != case.uploaded_by_user_id:
            raise LifecycleError("uploader_required")
        if case.status not in {"pending_employee_decision", "duplicate_blocked"}:
            raise LifecycleError("action_not_allowed")
        if action not in {"create", "replace", "publish_existing", "discard"}:
            raise LifecycleError("invalid_user_action")
        if case.status == "duplicate_blocked" and action not in {"publish_existing", "discard"}:
            raise LifecycleError("exact_duplicate_action_forbidden")
        if action == "discard":
            next_status = "withdrawn"
        elif case.requires_admin or action == "publish_existing":
            next_status = "pending_admin_approval"
        else:
            if not case.manager_user_id:
                next_status = "pending_admin_approval"
            else:
                next_status = "pending_manager_approval"
        with self.store.connect() as db:
            db.execute(
                """
                UPDATE document_cases
                SET requested_action = ?, status = ?, updated_at = ? WHERE case_id = ?
                """,
                (action, next_status, self.now(), case_id),
            )
            db.execute(
                "UPDATE document_versions SET status = ? WHERE version_id = ?",
                (next_status, case.version_id),
            )
            self._event(db, case_id, actor_user_id, "action_chosen", {"action": action, "status": next_status})
        return self.submission(case_id)

    def decide(
        self,
        *,
        case_id: str,
        actor_user_id: str,
        decision: Decision,
        reason: str,
    ) -> Submission:
        case = self.submission(case_id)
        actor = self.governance.identity(actor_user_id)
        reason = self._required(reason, "decision_reason")
        if decision not in {"approve", "reject", "escalate"}:
            raise LifecycleError("invalid_decision")
        if case.status == "pending_manager_approval":
            is_assigned_manager = actor_user_id == case.manager_user_id
            is_routed_delegate = (
                not is_assigned_manager
                and self.governance.may_approve_for_manager(actor_user_id, case.manager_user_id)
                and any(task.case_id == case_id for task in self.tasks_for(actor_user_id))
            )
            if not is_assigned_manager and not is_routed_delegate:
                raise LifecycleError("manager_required")
            if decision == "approve":
                next_status = "pending_admin_approval"
            elif decision == "escalate":
                next_status = "pending_admin_approval"
            else:
                next_status = "rejected"
        elif case.status == "pending_admin_approval":
            if actor.role not in {"admin", "portal_admin"}:
                raise LifecycleError("admin_required")
            next_status = "ready_to_activate" if decision == "approve" else "rejected"
        else:
            raise LifecycleError("decision_not_allowed")
        with self.store.connect() as db:
            db.execute(
                "UPDATE document_cases SET status = ?, updated_at = ? WHERE case_id = ?",
                (next_status, self.now(), case_id),
            )
            db.execute(
                "UPDATE document_versions SET status = ? WHERE version_id = ?",
                (next_status, case.version_id),
            )
            db.execute(
                """
                INSERT INTO document_decisions (
                    case_id, actor_user_id, actor_role, decision, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (case_id, actor_user_id, actor.role, decision, reason, self.now()),
            )
            self._event(db, case_id, actor_user_id, "decision_recorded", {"decision": decision, "status": next_status})
        return self.submission(case_id)

    def publish_existing(self, *, case_id: str, actor_user_id: str = "indexer") -> tuple[Submission, str, str | None]:
        case = self.submission(case_id)
        if case.status != "ready_to_activate" or case.requested_action != "publish_existing":
            raise LifecycleError("existing_publication_not_ready")
        with self.store.connect() as db:
            row = db.execute("SELECT analysis_json FROM document_cases WHERE case_id=?", (case_id,)).fetchone()
            analysis = json.loads(row["analysis_json"] or "{}")
            target_document_id = analysis.get("exact_duplicate_document_id") or analysis.get("normalized_duplicate_document_id")
            if not target_document_id or target_document_id == case.document_id:
                raise LifecycleError("existing_duplicate_target_required")
            target = db.execute(
                """SELECT d.active_version_id, v.status FROM canonical_documents d
                   JOIN document_versions v ON v.version_id=d.active_version_id
                   WHERE d.document_id=?""", (target_document_id,),
            ).fetchone()
            if not target or target["status"] != "active":
                raise LifecycleError("existing_duplicate_not_active")
            previous = db.execute(
                "SELECT status FROM document_publications WHERE document_id=? AND knowledgebase_id=?",
                (target_document_id, case.target_knowledgebase_id),
            ).fetchone()
            previous_status = previous["status"] if previous else None
            db.execute(
                """INSERT INTO document_publications(document_id,knowledgebase_id,status,created_at,updated_at)
                   VALUES (?,?,'active',?,?) ON CONFLICT(document_id,knowledgebase_id)
                   DO UPDATE SET status='active',updated_at=excluded.updated_at""",
                (target_document_id, case.target_knowledgebase_id, self.now(), self.now()),
            )
            db.execute(
                "UPDATE document_publications SET status='inactive',updated_at=? WHERE document_id=? AND knowledgebase_id=?",
                (self.now(), case.document_id, case.target_knowledgebase_id),
            )
            db.execute("UPDATE document_versions SET status='withdrawn_duplicate' WHERE version_id=?", (case.version_id,))
            db.execute("UPDATE document_cases SET status='active',updated_at=? WHERE case_id=?", (self.now(), case_id))
            self._event(db, case_id, actor_user_id, "existing_document_published", {
                "target_document_id": target_document_id,
                "target_version_id": target["active_version_id"],
                "knowledgebase_id": case.target_knowledgebase_id,
                "previous_publication_status": previous_status,
            })
        return self.submission(case_id), target["active_version_id"], previous_status

    def rollback_existing_publication(self, *, case_id: str, previous_status: str | None,
                                      reason: str, actor_user_id: str = "indexer") -> Submission:
        case = self.submission(case_id)
        with self.store.connect() as db:
            row = db.execute("SELECT analysis_json FROM document_cases WHERE case_id=?", (case_id,)).fetchone()
            analysis = json.loads(row["analysis_json"] or "{}")
            target_document_id = analysis.get("exact_duplicate_document_id") or analysis.get("normalized_duplicate_document_id")
            if previous_status is None:
                db.execute("DELETE FROM document_publications WHERE document_id=? AND knowledgebase_id=?",
                           (target_document_id, case.target_knowledgebase_id))
            else:
                db.execute("UPDATE document_publications SET status=?,updated_at=? WHERE document_id=? AND knowledgebase_id=?",
                           (previous_status, self.now(), target_document_id, case.target_knowledgebase_id))
            db.execute("UPDATE document_publications SET status='pending',updated_at=? WHERE document_id=? AND knowledgebase_id=?",
                       (self.now(), case.document_id, case.target_knowledgebase_id))
            db.execute("UPDATE document_versions SET status='ready_to_activate' WHERE version_id=?", (case.version_id,))
            db.execute("UPDATE document_cases SET status='ready_to_activate',updated_at=? WHERE case_id=?", (self.now(), case_id))
            self._event(db, case_id, actor_user_id, "existing_publication_rolled_back", {
                "target_document_id": target_document_id, "reason": reason,
            })
        return self.submission(case_id)

    def active_version(self, document_id: str) -> str | None:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT active_version_id FROM canonical_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        return row["active_version_id"] if row else None

    def rollback_activation(
        self, *, case_id: str, previous_version_id: str | None, reason: str,
        actor_user_id: str = "indexer",
    ) -> Submission:
        case = self.submission(case_id)
        if case.status != "active" or self.active_version(case.document_id) != case.version_id:
            raise LifecycleError("activation_rollback_not_allowed")
        with self.store.connect() as db:
            db.execute(
                "UPDATE document_versions SET status = 'ready_to_activate', valid_from = NULL, "
                "valid_until = NULL, activated_at = NULL WHERE version_id = ?",
                (case.version_id,),
            )
            if previous_version_id:
                db.execute(
                    "UPDATE document_versions SET status = 'active' WHERE version_id = ? AND document_id = ?",
                    (previous_version_id, case.document_id),
                )
            db.execute(
                "UPDATE canonical_documents SET active_version_id = ?, updated_at = ? WHERE document_id = ?",
                (previous_version_id, self.now(), case.document_id),
            )
            publication_status = "active" if previous_version_id else "pending"
            db.execute(
                "UPDATE document_publications SET status = ?, updated_at = ? "
                "WHERE document_id = ? AND knowledgebase_id = ?",
                (publication_status, self.now(), case.document_id, case.target_knowledgebase_id),
            )
            db.execute(
                "UPDATE document_cases SET status = 'ready_to_activate', updated_at = ? WHERE case_id = ?",
                (self.now(), case_id),
            )
            self._event(db, case_id, actor_user_id, "activation_rolled_back", {
                "reason": reason, "restored_version_id": previous_version_id,
            })
        return self.submission(case_id)

    def activate(self, *, case_id: str, actor_user_id: str = "indexer") -> Submission:
        case = self.submission(case_id)
        if case.status != "ready_to_activate":
            raise LifecycleError("activation_not_ready")
        valid_from = self.today()
        valid_until = add_workdays(valid_from, case.valid_workdays, self.holidays)
        with self.store.connect() as db:
            previous = db.execute(
                "SELECT active_version_id FROM canonical_documents WHERE document_id = ?",
                (case.document_id,),
            ).fetchone()["active_version_id"]
            if previous and previous != case.version_id:
                db.execute(
                    "UPDATE document_versions SET status = 'superseded' WHERE version_id = ?",
                    (previous,),
                )
            db.execute(
                """
                UPDATE document_versions
                SET status = 'active', valid_from = ?, valid_until = ?, activated_at = ?
                WHERE version_id = ?
                """,
                (valid_from.isoformat(), valid_until.isoformat(), self.now(), case.version_id),
            )
            db.execute(
                "UPDATE canonical_documents SET active_version_id = ?, updated_at = ? WHERE document_id = ?",
                (case.version_id, self.now(), case.document_id),
            )
            db.execute(
                """
                UPDATE document_publications SET status = 'active', updated_at = ?
                WHERE document_id = ? AND knowledgebase_id = ?
                """,
                (self.now(), case.document_id, case.target_knowledgebase_id),
            )
            db.execute(
                "UPDATE document_cases SET status = 'active', updated_at = ? WHERE case_id = ?",
                (self.now(), case_id),
            )
            self._event(db, case_id, actor_user_id, "activated", {"valid_until": valid_until.isoformat(), "superseded": previous})
        return self.submission(case_id)

    def submission(self, case_id: str) -> Submission:
        with self.store.connect() as db:
            row = db.execute(
                """
                SELECT c.*, d.owner_user_id, d.title, d.confidentiality,
                       v.original_filename, v.original_sha256, v.valid_workdays
                FROM document_cases c
                JOIN canonical_documents d USING (document_id)
                JOIN document_versions v USING (version_id)
                WHERE c.case_id = ?
                """,
                (case_id,),
            ).fetchone()
        if not row:
            raise LifecycleError("unknown_case")
        return Submission(
            case_id=row["case_id"],
            document_id=row["document_id"],
            version_id=row["version_id"],
            owner_user_id=row["owner_user_id"],
            uploaded_by_user_id=row["uploaded_by_user_id"],
            target_knowledgebase_id=row["target_knowledgebase_id"],
            title=row["title"],
            original_filename=row["original_filename"],
            original_sha256=row["original_sha256"],
            valid_workdays=int(row["valid_workdays"]),
            confidentiality=row["confidentiality"],
            status=row["status"],
            requested_action=row["requested_action"],
            manager_user_id=row["manager_user_id"],
            requires_admin=bool(row["requires_admin"]),
        )

    def tasks_for(self, actor_user_id: str) -> list[Submission]:
        actor = self.governance.identity(actor_user_id)
        today = self.today().isoformat()
        with self.store.connect() as db:
            if actor.role in {"admin", "portal_admin"}:
                rows = db.execute(
                    """SELECT case_id FROM document_cases
                       WHERE status IN ('pending_admin_approval','security_blocked','needs_correction','error')
                          OR (status='pending_manager_approval' AND requires_admin=1)
                       ORDER BY updated_at"""
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT case_id FROM document_cases
                       WHERE (uploaded_by_user_id = ? AND status IN ('pending_employee_decision','duplicate_blocked'))
                          OR (manager_user_id = ? AND status = 'pending_manager_approval')
                       ORDER BY updated_at""",
                    (actor_user_id, actor_user_id),
                ).fetchall()
                delegated = db.execute(
                    """SELECT manager_user_id FROM manager_delegates
                       WHERE delegate_user_id = ?
                         AND (valid_from IS NULL OR valid_from <= ?)
                         AND (valid_until IS NULL OR valid_until >= ?)""",
                    (actor_user_id, today, today),
                ).fetchall()
                manager_ids = [row["manager_user_id"] for row in delegated]
                if manager_ids:
                    placeholders = ",".join("?" for _ in manager_ids)
                    candidates = db.execute(
                        f"SELECT case_id, manager_user_id, created_at FROM document_cases "
                        f"WHERE status = 'pending_manager_approval' AND manager_user_id IN ({placeholders}) "
                        f"ORDER BY updated_at", manager_ids,
                    ).fetchall()
                    absent = {item["manager_user_id"] for item in db.execute(
                        f"SELECT manager_user_id FROM manager_absences WHERE manager_user_id IN ({placeholders}) "
                        f"AND absent_from <= ? AND absent_until >= ?", (*manager_ids, today, today),
                    ).fetchall()}
                    delegated_rows = [item for item in candidates if item["manager_user_id"] in absent
                                      or self._workdays_since(item["created_at"]) >= 4]
                    known = {row["case_id"] for row in rows}
                    rows = list(rows) + [row for row in delegated_rows if row["case_id"] not in known]
        return [self.submission(row["case_id"]) for row in rows]

    def _workdays_since(self, timestamp: str) -> int:
        started = date.fromisoformat(timestamp[:10])
        current, count = started, 0
        while current < self.today():
            current += timedelta(days=1)
            if _is_workday(current, self.holidays):
                count += 1
        return count

    def source_record(self, version_id: str, actor_user_id: str) -> dict[str, Any]:
        self.governance.identity(actor_user_id)
        allowed = set(self.governance.allowed_knowledgebases(actor_user_id, "read"))
        with self.store.connect() as db:
            row = db.execute(
                """SELECT v.*, d.active_version_id, d.title
                   FROM document_versions v JOIN canonical_documents d USING (document_id)
                   WHERE v.version_id = ?""", (version_id,),
            ).fetchone()
            if not row or row["status"] != "active" or row["active_version_id"] != version_id:
                raise LifecycleError("source_not_available")
            publications = db.execute(
                """SELECT knowledgebase_id FROM document_publications
                   WHERE document_id = ? AND status = 'active'""", (row["document_id"],),
            ).fetchall()
        visible = sorted(allowed.intersection(item["knowledgebase_id"] for item in publications))
        if not visible:
            raise LifecycleError("source_read_access_required")
        return {**dict(row), "visible_knowledgebase_ids": visible}

    def version_record(self, version_id: str) -> dict[str, Any]:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM document_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
        if not row:
            raise LifecycleError("unknown_version")
        return dict(row)

    def _event(
        self,
        db,
        case_id: str,
        actor_user_id: str,
        event_type: str,
        details: dict[str, Any],
    ) -> None:
        db.execute(
            """
            INSERT INTO document_events (
                case_id, actor_user_id, event_type, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (case_id, actor_user_id, event_type, json.dumps(details, ensure_ascii=False, sort_keys=True), self.now()),
        )

    @staticmethod
    def _required(value: Any, field: str) -> str:
        clean = str(value or "").strip()
        if not clean:
            raise LifecycleError(f"{field}_required")
        return clean

    @classmethod
    def _sha256(cls, value: Any) -> str:
        clean = cls._required(value, "sha256").lower()
        if len(clean) != 64 or any(character not in "0123456789abcdef" for character in clean):
            raise LifecycleError("invalid_sha256")
        return clean
