#!/usr/bin/env python3
"""Static safety contracts for the encrypted backup automation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "backup-automated.sh"
SERVICE = ROOT / "systemd" / "kahle-vinci-backup.service"
TIMER = ROOT / "systemd" / "kahle-vinci-backup.timer"


def test_backup_script_safety_contract():
    src = SCRIPT.read_text(encoding="utf-8")

    assert "set -Eeuo pipefail" in src
    assert "if (( EUID != 0 ))" in src
    assert "trap cleanup EXIT" in src
    assert src.index('install -d -o root -g root -m 700 "$STAGING_DIR" "$STATUS_DIR"') < src.index("trap cleanup EXIT")
    assert "restart_stack || true" in src
    assert "compose up -d --wait --wait-timeout 120" in src
    assert "flock -n 9" in src
    assert "age --recipient" in src
    assert 'mv -- "$PARTIAL_FILE" "$OUTPUT_FILE"' in src
    assert 'sha256sum "$(basename "$OUTPUT_FILE")"' in src
    assert "sha256sum -c SHA256SUMS.txt" in src


def test_only_encrypted_outputs_are_shared_with_backup_reader_group():
    src = SCRIPT.read_text(encoding="utf-8")

    assert 'BACKUP_READER_GROUP="${BACKUP_READER_GROUP:-kahle-backup-readers}"' in src
    assert 'install -d -o root -g "$BACKUP_READER_GROUP" -m 710 "$BACKUP_ROOT"' in src
    assert 'install -d -o root -g root -m 700 "$STAGING_DIR" "$STATUS_DIR"' in src
    assert 'install -d -o root -g "$BACKUP_READER_GROUP" -m 750 "$ENCRYPTED_DIR"' in src
    assert 'chgrp "$BACKUP_READER_GROUP" "$OUTPUT_FILE" "$OUTPUT_HASH"' in src
    assert 'chmod 640 "$OUTPUT_FILE" "$OUTPUT_HASH"' in src
    assert "BACKUP_COMPLETE=1" in src
    assert 'rm -rf -- "$STAGING_DIR"' in src
    assert "-mtime \"+$RETENTION_DAYS\" -delete" in src


def test_systemd_contract():
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")

    assert "ExecStart=/usr/local/sbin/kahle-vinci-backup" in service
    assert "TimeoutStartSec=2h" in service
    assert "OnCalendar=*-*-* 02:30:00 Europe/Berlin" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=15m" in timer

