from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from .backup_restore import create_backup, decode_key, restore_backup, validate_restored_portal
    from .maintenance import MaintenanceService
    from .portal_governance import SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from backup_restore import create_backup, decode_key, restore_backup, validate_restored_portal
    from maintenance import MaintenanceService
    from portal_governance import SQLiteGovernanceStore


PORTAL_ROOT = Path(os.getenv("KB_PORTAL_ROOT", "/portal-data"))
STATE_ROOT = Path(os.getenv("KB_SYNC_STATE_ROOT", "/kb-sync-state"))
PRIMARY = Path(os.getenv("KB_BACKUP_PRIMARY_ROOT", "/backups/primary"))
SECONDARY = Path(os.getenv("KB_BACKUP_SECONDARY_ROOT", "/backups-secondary"))
STATE_PATH = PRIMARY / "backup-state.json"


def _notify_admins(service: MaintenanceService, kind: str, message: str, key: str) -> None:
    with service.store.connect() as db:
        recipients = [row["email"] for row in db.execute(
            "SELECT email FROM portal_users WHERE active = 1 AND role IN ('admin','portal_admin')"
        ).fetchall()]
    for recipient in recipients:
        service.enqueue_notification(recipient, kind, "KAHLE-Vinci: Backupfehler", message, dedupe_key=key)


def run_backup(key: bytes, *, today: date | None = None) -> dict:
    today = today or date.today()
    PRIMARY.mkdir(parents=True, exist_ok=True); SECONDARY.mkdir(parents=True, exist_ok=True)
    filename = f"kahle-vinci-{today.isoformat()}.kahlebackup"
    result = create_backup({"portal-data": PORTAL_ROOT, "kb-sync-state": STATE_ROOT}, PRIMARY / filename, key)
    secondary = SECONDARY / filename
    temporary = secondary.with_suffix(secondary.suffix + ".tmp")
    shutil.copy2(result.path, temporary); temporary.replace(secondary)
    return {"date": today.isoformat(), "file": filename, "sha256": result.sha256, "files": result.files}


def run_restore_test(backup: Path, key: bytes) -> None:
    with tempfile.TemporaryDirectory() as directory:
        restored = Path(directory) / "restored"
        restore_backup(backup, restored, key)
        validate_restored_portal(restored)


def main() -> None:
    key = decode_key(os.environ["KB_BACKUP_ENCRYPTION_KEY"])
    service = MaintenanceService(SQLiteGovernanceStore(PORTAL_ROOT / "wissensportal.sqlite3"))
    while True:
        today = date.today()
        state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
        try:
            if state.get("last_backup") != today.isoformat():
                record = run_backup(key, today=today)
                state.update({"last_backup": today.isoformat(), "last_result": record})
            month = today.strftime("%Y-%m")
            if state.get("last_restore_test") != month and state.get("last_result"):
                run_restore_test(PRIMARY / state["last_result"]["file"], key)
                state["last_restore_test"] = month
            STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as exc:
            incident = datetime.now(timezone.utc).strftime("backup-%Y%m%d%H%M")
            _notify_admins(service, "backup_failure", f"Backup oder Restore-Test fehlgeschlagen. Referenz: {incident}", incident)
            print(f"backup_cycle_failed incident={incident} error={exc}", flush=True)
        time.sleep(max(300, int(os.getenv("KB_BACKUP_INTERVAL_SECONDS", "3600"))))


if __name__ == "__main__":
    main()
