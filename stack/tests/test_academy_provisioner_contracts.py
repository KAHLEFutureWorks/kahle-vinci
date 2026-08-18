from __future__ import annotations

from pathlib import Path


STACK_ROOT = Path(__file__).resolve().parents[1]


def _service_block(compose: str) -> str:
    return compose.split("  academy-provisioner:\n", 1)[1].split("\n  n8n:\n", 1)[0]


def test_academy_provisioner_is_isolated_and_has_no_public_port() -> None:
    compose = (STACK_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    block = _service_block(compose)

    assert "context: ./academy-provisioner" in block
    assert "- open-webui:/open-webui-data:ro" in block
    assert "- academy_provisioner_state:/state" in block
    assert "read_only: true" in block
    assert "no-new-privileges:true" in block
    assert "cap_drop:" in block and "- ALL" in block
    assert "ports:" not in block
    assert 'test: ["CMD", "python", "-m", "app.healthcheck"]' in block


def test_academy_provisioner_requires_key_and_uses_exact_course_name() -> None:
    compose = (STACK_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    environment = (STACK_ROOT / "env.production.template").read_text(encoding="utf-8")

    assert "LEARNINGSUITE_API_KEY: ${LEARNINGSUITE_API_KEY:?LEARNINGSUITE_API_KEY is required}" in compose
    assert (
        "LEARNINGSUITE_ALLOWED_EMAILS: "
        "${LEARNINGSUITE_ALLOWED_EMAILS:?LEARNINGSUITE_ALLOWED_EMAILS is required}"
    ) in compose
    assert "Einführung in die KAHLE-Vinci Nutzung" in compose
    assert "LEARNINGSUITE_API_KEY=<secret>" in environment
    assert "LEARNINGSUITE_ALLOWED_EMAILS=<test-email>@kahle.de" in environment
    assert "KB_MAIL_TENANT_ID: ${KB_MAIL_TENANT_ID:?KB_MAIL_TENANT_ID is required}" in compose
    assert "KB_MAIL_CLIENT_ID: ${KB_MAIL_CLIENT_ID:?KB_MAIL_CLIENT_ID is required}" in compose
    assert "KB_MAIL_CLIENT_SECRET: ${KB_MAIL_CLIENT_SECRET:?KB_MAIL_CLIENT_SECRET is required}" in compose
    assert "VINCI_WELCOME_MAIL_SENDER: ${VINCI_WELCOME_MAIL_SENDER:-oltmanns@kahle.de}" in compose
    assert "VINCI_WELCOME_MAIL_SENDER=oltmanns@kahle.de" in environment


def test_production_limits_are_defined_for_academy_provisioner() -> None:
    production_compose = (STACK_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    block = production_compose.split("  academy-provisioner:\n", 1)[1].split("\n  n8n:\n", 1)[0]

    assert "mem_limit: 256m" in block
    assert "cpus: 0.5" in block
    assert "pids_limit: 128" in block
