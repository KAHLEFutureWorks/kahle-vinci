#!/usr/bin/env python3
"""Static safety contracts for KAHLE-Vinci health monitoring."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "healthcheck-automated.sh"
SERVICE = ROOT / "systemd" / "kahle-vinci-healthcheck.service"
TIMER = ROOT / "systemd" / "kahle-vinci-healthcheck.timer"


def test_healthcheck_contract():
    src = SCRIPT.read_text(encoding="utf-8")

    assert "set -Eeuo pipefail" in src
    assert "flock -n 9" in src
    assert "muss eine ganze Zahl zwischen 1 und 100 sein" in src
    assert "kahle-vinci-backup.service" in src
    assert "backup-in-progress" in src
    assert "caddy" in src
    assert "open-webui" in src
    assert "https://vinci.kahle.de/healthz" in src
    assert "http://127.0.0.1:3001/health" in src
    assert "http://127.0.0.1:5678/healthz" in src
    assert "http://127.0.0.1:6333/healthz" in src
    assert "http://127.0.0.1:8091/health" in src
    assert "last successful backup is too old" in src
    assert "latest backup attempt failed" in src
    assert "expected public IPv4 listener missing" in src
    assert "unexpected public IPv6 listener" in src
    assert "localhost-only port is publicly bound" in src
    assert "awk '{print $4}'" in src


def test_systemd_contract():
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")

    assert "ExecStart=/usr/local/sbin/kahle-vinci-healthcheck" in service
    assert "TimeoutStartSec=90s" in service
    assert "OnUnitActiveSec=5m" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=30s" in timer

