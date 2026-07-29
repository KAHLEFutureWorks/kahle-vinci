#!/usr/bin/env python3
"""Static safety contracts for the Healthchecks.io reporter."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "healthchecks-run.sh"
HEALTH_DROPIN = (
    ROOT / "systemd" / "kahle-vinci-healthcheck.service.d" / "healthchecks.conf"
)
BACKUP_DROPIN = ROOT / "systemd" / "kahle-vinci-backup.service.d" / "healthchecks.conf"


def test_reporter_contract():
    src = SCRIPT.read_text(encoding="utf-8")

    assert "set -uo pipefail" in src
    assert "https://hc-ping\\.com/" in src
    assert 'send_ping "/start"' in src
    assert 'send_ping "" "success"' in src
    assert 'send_ping "/fail" "failure"' in src
    assert "--retry 2" in src
    assert "--connect-timeout 5" in src
    assert "--max-time 15" in src
    assert 'exit "$EXIT_STATUS"' in src
    assert "data-binary @" not in src
    assert "journalctl" not in src


def test_dropin_contracts():
    health = HEALTH_DROPIN.read_text(encoding="utf-8")
    backup = BACKUP_DROPIN.read_text(encoding="utf-8")

    for text in (health, backup):
        assert "EnvironmentFile=/etc/kahle-vinci/healthchecks.env" in text
        assert "ExecStart=\n" in text
        assert "/usr/local/sbin/kahle-vinci-healthchecks-run" in text

    assert "HEALTHCHECK_SERVER_URL" in health
    assert "/usr/local/sbin/kahle-vinci-healthcheck" in health
    assert "HEALTHCHECK_BACKUP_URL" in backup
    assert "/usr/local/sbin/kahle-vinci-backup" in backup

