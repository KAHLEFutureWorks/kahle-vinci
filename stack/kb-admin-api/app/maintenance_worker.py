from __future__ import annotations

import os
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

try:
    from .mail_delivery import MicrosoftGraphMailTransport, OutboxDispatcher
    from .maintenance import MaintenanceService, is_workday
    from .portal_governance import SQLiteGovernanceStore
    from .quality_cases import QualityCaseService
except ImportError:  # pragma: no cover
    from mail_delivery import MicrosoftGraphMailTransport, OutboxDispatcher
    from maintenance import MaintenanceService, is_workday
    from portal_governance import SQLiteGovernanceStore
    from quality_cases import QualityCaseService


BERLIN = ZoneInfo("Europe/Berlin")
DB_PATH = Path(os.getenv("KB_PORTAL_DB_PATH", "/portal-data/wissensportal.sqlite3"))
FILES_ROOT = Path(os.getenv("KB_PORTAL_FILES_ROOT", "/portal-data/files"))
SYNC_URL = os.getenv("KB_SYNC_URL", "http://kb-sync:8093").rstrip("/")
SYNC_KEY = os.getenv("KB_SYNC_INTERNAL_API_KEY", "")


def reindex() -> None:
    response = requests.post(
        f"{SYNC_URL}/reindex-all", headers={"X-API-Key": SYNC_KEY}, timeout=300,
    )
    response.raise_for_status()


def expiry_digest_due(now: datetime, last_digest_date: date | None) -> bool:
    local = now.astimezone(BERLIN)
    return (
        is_workday(local.date())
        and (local.hour, local.minute) >= (10, 30)
        and last_digest_date != local.date()
    )


def run_once(service: MaintenanceService, dispatcher: OutboxDispatcher | None,
             *, generate_expiry_digest: bool = True) -> None:
    if generate_expiry_digest:
        service.generate_expiry_digest()
    service.process_pending_approvals()
    changed = service.expire_due_versions()
    trash = service.process_trash(FILES_ROOT)
    service.enforce_retention()
    if changed or trash["deleted"]:
        reindex()
    if dispatcher:
        dispatcher.dispatch()


def main() -> None:
    store = SQLiteGovernanceStore(DB_PATH)
    QualityCaseService(store)
    service = MaintenanceService(store, today=lambda: datetime.now(BERLIN).date())
    dispatcher = None
    graph = (
        os.getenv("KB_MAIL_TENANT_ID", ""), os.getenv("KB_MAIL_CLIENT_ID", ""),
        os.getenv("KB_MAIL_CLIENT_SECRET", ""), os.getenv("KB_MAIL_SENDER", ""),
    )
    if all(graph):
        dispatcher = OutboxDispatcher(service, MicrosoftGraphMailTransport(*graph))
    last_expiry_digest: date | None = None
    while True:
        now = datetime.now(BERLIN)
        digest_due = expiry_digest_due(now, last_expiry_digest)
        try:
            run_once(service, dispatcher, generate_expiry_digest=digest_due)
            if digest_due:
                last_expiry_digest = now.date()
        except Exception as exc:
            print(f"maintenance_cycle_failed error={exc}", flush=True)
        time.sleep(max(60, int(os.getenv("KB_MAINTENANCE_INTERVAL_SECONDS", "300"))))


if __name__ == "__main__":
    main()
