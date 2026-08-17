from __future__ import annotations

from datetime import date
from typing import Any, Protocol

try:
    from .portal_governance import PortalGovernance, SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import PortalGovernance, SQLiteGovernanceStore


class AutomaticRepliesReader(Protocol):
    def automatic_replies(self, user_principal_name: str) -> dict[str, Any]: ...


def sync_outlook_absences(store: SQLiteGovernanceStore, client: AutomaticRepliesReader,
                          *, today: date) -> dict[str, int]:
    """Pull Outlook automatic replies for portal approvers into routing state."""
    governance = PortalGovernance(store)
    with store.connect() as db:
        users = db.execute(
            "SELECT user_id,email FROM portal_users WHERE active=1 "
            "AND role IN ('manager','admin','portal_admin') ORDER BY user_id"
        ).fetchall()
    results: dict[str, int] = {}
    for user in users:
        try:
            setting = client.automatic_replies(user["email"])
            status = str(setting.get("status") or "disabled").lower()
            if status == "scheduled":
                start = str((setting.get("scheduledStartDateTime") or {}).get("dateTime") or "")[:10]
                end = str((setting.get("scheduledEndDateTime") or {}).get("dateTime") or "")[:10]
                result = governance.sync_outlook_absence(user["user_id"], start, end)
            elif status == "alwaysenabled":
                result = governance.sync_outlook_absence(
                    user["user_id"], today.isoformat(), "9999-12-31",
                )
            else:
                result = governance.sync_outlook_absence(user["user_id"], None, None)
        except Exception as exc:
            result = "failed"
            print(f"outlook_absence_sync_failed user={user['user_id']} error={exc}", flush=True)
        results[result] = results.get(result, 0) + 1
    return results
