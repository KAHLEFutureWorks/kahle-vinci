from __future__ import annotations

import os
import time
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import requests

try:
    from .mail_delivery import (
        LocalMailCaptureTransport, MicrosoftGraphClient, MicrosoftGraphMailTransport,
        OutboxDispatcher,
    )
    from .maintenance import MaintenanceService, is_workday
    from .outlook_absence import sync_outlook_absences
    from .portal_governance import SQLiteGovernanceStore
    from .quality_cases import QualityCaseService
except ImportError:  # pragma: no cover
    from mail_delivery import (
        LocalMailCaptureTransport, MicrosoftGraphClient, MicrosoftGraphMailTransport,
        OutboxDispatcher,
    )
    from maintenance import MaintenanceService, is_workday
    from outlook_absence import sync_outlook_absences
    from portal_governance import SQLiteGovernanceStore
    from quality_cases import QualityCaseService


BERLIN = ZoneInfo("Europe/Berlin")
DB_PATH = Path(os.getenv("KB_PORTAL_DB_PATH", "/portal-data/wissensportal.sqlite3"))
FILES_ROOT = Path(os.getenv("KB_PORTAL_FILES_ROOT", "/portal-data/files"))
SYNC_URL = os.getenv("KB_SYNC_URL", "http://kb-sync:8093").rstrip("/")
SYNC_KEY = os.getenv("KB_SYNC_INTERNAL_API_KEY", "")


def sync_document(document_id: str) -> None:
    response = requests.post(
        f"{SYNC_URL}/hybrid/documents/sync", json={"document_id": document_id},
        headers={"X-API-Key": SYNC_KEY}, timeout=180,
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
             *, generate_expiry_digest: bool = True,
             absence_sync: Callable[[], object] | None = None) -> None:
    if absence_sync:
        absence_sync()
    if generate_expiry_digest:
        service.generate_expiry_digest()
    service.process_pending_approvals()
    changed = service.expire_due_versions()
    service.purge_superseded_version_files(FILES_ROOT)
    trash = service.process_trash(FILES_ROOT)
    migration_expired = service.process_migration_deadlines()
    service.enforce_retention()
    # Expiry and final deletion are document-local changes. Legacy transition
    # entries are not part of the canonical portal index until approved.
    for document_id in dict.fromkeys([*changed, *trash["deleted"]]):
        sync_document(document_id)
    if dispatcher:
        dispatcher.dispatch()


def main() -> None:
    store = SQLiteGovernanceStore(DB_PATH)
    QualityCaseService(store)
    service = MaintenanceService(store, today=lambda: datetime.now(BERLIN).date())
    dispatcher = None
    graph_credentials = (
        os.getenv("KB_MAIL_TENANT_ID", "") or os.getenv("MICROSOFT_CLIENT_TENANT_ID", ""),
        os.getenv("KB_MAIL_CLIENT_ID", "") or os.getenv("MICROSOFT_CLIENT_ID", ""),
        os.getenv("KB_MAIL_CLIENT_SECRET", "") or os.getenv("MICROSOFT_CLIENT_SECRET", ""),
    )
    mail_sender = os.getenv("KB_MAIL_SENDER", "")
    graph_client = MicrosoftGraphClient(*graph_credentials) if all(graph_credentials) else None
    if graph_client and mail_sender:
        dispatcher = OutboxDispatcher(
            service, MicrosoftGraphMailTransport(*graph_credentials, mail_sender),
        )
    elif capture_path := os.getenv("KB_MAIL_CAPTURE_PATH", "").strip():
        dispatcher = OutboxDispatcher(service, LocalMailCaptureTransport(Path(capture_path)))
    last_expiry_digest: date | None = None
    absence_sync = None
    if graph_client and os.getenv("KB_GRAPH_ABSENCE_SYNC_ENABLED", "false").lower() == "true":
        def run_absence_sync() -> None:
            result = sync_outlook_absences(
                store, graph_client, today=datetime.now(BERLIN).date(),
            )
            if result.get("failed") or result.get("delegate_required"):
                print(f"outlook_absence_sync_attention result={result}", flush=True)
        absence_sync = run_absence_sync
    while True:
        now = datetime.now(BERLIN)
        digest_due = expiry_digest_due(now, last_expiry_digest)
        try:
            run_once(
                service, dispatcher, generate_expiry_digest=digest_due,
                absence_sync=absence_sync,
            )
            if digest_due:
                last_expiry_digest = now.date()
        except Exception as exc:
            print(f"maintenance_cycle_failed error={exc}", flush=True)
            traceback.print_exc()
        time.sleep(max(60, int(os.getenv("KB_MAINTENANCE_INTERVAL_SECONDS", "300"))))


if __name__ == "__main__":
    main()
