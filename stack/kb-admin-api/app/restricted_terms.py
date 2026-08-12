from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from typing import Callable

try:
    from .portal_governance import PortalGovernance
except ImportError:  # pragma: no cover
    from portal_governance import PortalGovernance


class RestrictedTermError(ValueError):
    pass


@dataclass(frozen=True)
class RestrictedTerm:
    rule_id: str
    term: str
    active: bool
    created_by: str
    created_at: str


class RestrictedTermService:
    """Admin-managed terms that force uploaded knowledge into admin review."""

    DEFAULT_TERMS = ("TPI", "Reparaturleitfaden")

    def __init__(self, governance: PortalGovernance, identifier: Callable[[], str] | None = None):
        self.governance = governance
        self.identifier = identifier or (lambda: str(uuid.uuid4()))
        self._initialize()

    def _initialize(self) -> None:
        with self.governance.store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS restricted_document_terms (
                rule_id TEXT PRIMARY KEY, term TEXT NOT NULL, normalized_term TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            count = db.execute("SELECT COUNT(*) FROM restricted_document_terms").fetchone()[0]
            if count == 0:
                now = self.governance.now()
                for term in self.DEFAULT_TERMS:
                    db.execute(
                        "INSERT INTO restricted_document_terms VALUES (?,?,?,?,?,?,?)",
                        (self.identifier(), term, self._normalize(term), 1, "system", now, now),
                    )

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.casefold().split())

    def _require_admin(self, actor_user_id: str) -> None:
        if self.governance.identity(actor_user_id).role not in {"admin", "portal_admin"}:
            raise RestrictedTermError("admin_required")

    def list(self, actor_user_id: str) -> list[RestrictedTerm]:
        self._require_admin(actor_user_id)
        with self.governance.store.connect() as db:
            rows = db.execute(
                "SELECT rule_id,term,active,created_by,created_at FROM restricted_document_terms ORDER BY normalized_term"
            ).fetchall()
        return [RestrictedTerm(row["rule_id"], row["term"], bool(row["active"]), row["created_by"], row["created_at"]) for row in rows]

    def add(self, actor_user_id: str, term: str) -> RestrictedTerm:
        self._require_admin(actor_user_id)
        clean = " ".join(term.split())
        normalized = self._normalize(clean)
        if len(clean) < 2 or len(clean) > 120:
            raise RestrictedTermError("restricted_term_length_invalid")
        with self.governance.store.connect() as db:
            if db.execute(
                "SELECT 1 FROM restricted_document_terms WHERE normalized_term=?", (normalized,)
            ).fetchone():
                raise RestrictedTermError("restricted_term_exists")
        now, rule_id = self.governance.now(), self.identifier()
        try:
            with self.governance.store.connect() as db:
                db.execute(
                    "INSERT INTO restricted_document_terms VALUES (?,?,?,?,?,?,?)",
                    (rule_id, clean, normalized, 1, actor_user_id, now, now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise RestrictedTermError("restricted_term_exists") from exc
            raise
        self.governance.record_audit(actor_user_id, "restricted_term_added", "restricted_term", rule_id, {"term": clean})
        return RestrictedTerm(rule_id, clean, True, actor_user_id, now)

    def remove(self, actor_user_id: str, rule_id: str) -> None:
        self._require_admin(actor_user_id)
        with self.governance.store.connect() as db:
            row = db.execute("SELECT term FROM restricted_document_terms WHERE rule_id=?", (rule_id,)).fetchone()
            if not row:
                raise RestrictedTermError("restricted_term_unknown")
            db.execute("DELETE FROM restricted_document_terms WHERE rule_id=?", (rule_id,))
        self.governance.record_audit(actor_user_id, "restricted_term_removed", "restricted_term", rule_id, {"term": row["term"]})

    def matches(self, text: str) -> tuple[str, ...]:
        normalized_text = self._normalize(text)
        with self.governance.store.connect() as db:
            rows = db.execute(
                "SELECT term,normalized_term FROM restricted_document_terms WHERE active=1 ORDER BY normalized_term"
            ).fetchall()
        found = []
        for row in rows:
            escaped = re.escape(row["normalized_term"])
            if re.search(rf"(?<!\w){escaped}(?!\w)", normalized_text, flags=re.UNICODE):
                found.append(row["term"])
        return tuple(found)

    def serialized(self, actor_user_id: str) -> list[dict[str, object]]:
        return [asdict(item) for item in self.list(actor_user_id)]
