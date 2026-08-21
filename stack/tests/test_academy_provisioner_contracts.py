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
    assert "MICROSOFT_CLIENT_TENANT_ID: ${MICROSOFT_CLIENT_TENANT_ID:?MICROSOFT_CLIENT_TENANT_ID is required}" in compose
    assert "MICROSOFT_CLIENT_ID: ${MICROSOFT_CLIENT_ID:?MICROSOFT_CLIENT_ID is required}" in compose
    assert "MICROSOFT_CLIENT_SECRET: ${MICROSOFT_CLIENT_SECRET:?MICROSOFT_CLIENT_SECRET is required}" in compose
    assert "VINCI_WELCOME_MAIL_SENDER: ${VINCI_WELCOME_MAIL_SENDER:-oltmanns@kahle.de}" in compose
    assert "VINCI_WELCOME_MAIL_SENDER=oltmanns@kahle.de" in environment


def test_production_limits_are_defined_for_academy_provisioner() -> None:
    production_compose = (STACK_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    block = production_compose.split("  academy-provisioner:\n", 1)[1].split("\n  n8n:\n", 1)[0]

    assert "mem_limit: 256m" in block
    assert "cpus: 0.5" in block
    assert "pids_limit: 128" in block


def test_local_stack_disables_academy_provisioning_and_resolves_required_placeholders() -> None:
    local_compose = (STACK_ROOT / "docker-compose.local-edge.yml").read_text(encoding="utf-8")
    local_start = (STACK_ROOT.parent / "scripts" / "start-stack.ps1").read_text(encoding="utf-8")

    local_block = local_compose.split("  academy-provisioner:\n", 1)[1].split(
        "\n  caddy-local:\n", 1
    )[0]
    assert 'profiles: ["production-only"]' in local_block
    for variable in (
        "LEARNINGSUITE_API_KEY",
        "LEARNINGSUITE_ALLOWED_EMAILS",
        "MICROSOFT_CLIENT_TENANT_ID",
        "MICROSOFT_CLIENT_ID",
        "MICROSOFT_CLIENT_SECRET",
    ):
        assert f'{variable} = "local-disabled"' in local_start
    assert 'if ([Environment]::GetEnvironmentVariable($name) -eq "local-disabled")' in local_start
    assert 'Remove-Item -Path "Env:$name"' in local_start


def test_local_stack_imports_the_current_user_ionos_token() -> None:
    local_start = (STACK_ROOT.parent / "scripts" / "start-stack.ps1").read_text(encoding="utf-8")

    assert "GetEnvironmentVariable(\"IONOS_API_TOKEN\", \"User\")" in local_start
    assert 'Set-Item -Path "Env:IONOS_API_TOKEN"' in local_start
    assert "$importedIonosApiToken" in local_start
