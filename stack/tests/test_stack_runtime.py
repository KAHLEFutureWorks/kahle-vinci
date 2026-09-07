from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts" / "StackRuntime.psm1"
START_SCRIPT = ROOT / "scripts" / "start-stack.ps1"


def powershell() -> str:
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if not executable:
        pytest.skip("PowerShell is required to exercise stack runtime checks")
    return executable


def run_powershell(expression: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            powershell(),
            "-NoProfile",
            "-Command",
            f"Import-Module '{MODULE}' -Force; {expression}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_foreign_fixed_name_container_is_reported_before_compose_up():
    result = run_powershell(
        "$containers = @("
        "[pscustomobject]@{ Name = 'kb-admin-dashboard'; Project = '' },"
        "[pscustomobject]@{ Name = 'open-webui'; Project = 'stack' }"
        "); "
        "Find-ForeignContainerNames -Containers $containers -ComposeProject 'stack' "
        "| ConvertTo-Json -Compress"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == "kb-admin-dashboard"


def test_empty_container_inventory_is_valid_before_first_compose_start():
    result = run_powershell(
        "$containers = @(); "
        "$foreign = @(Find-ForeignContainerNames -Containers $containers "
        "-ComposeProject 'stack'); 'count=' + $foreign.Count"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "count=0"


def test_start_script_skips_foreign_container_binding_for_empty_inventory():
    source = START_SCRIPT.read_text(encoding="utf-8")

    assert "if ($existingContainers.Count -gt 0)" in source


def test_local_compose_project_name_ignores_ambient_project_name():
    result = run_powershell(
        "$env:COMPOSE_PROJECT_NAME = 'stale-project'; "
        "Get-LocalComposeProjectName -ComposeFile "
        "'C:/kahle-vinci/stack/docker-compose.yml'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "stack"


@pytest.mark.parametrize(
    "container_expression",
    (
        "[pscustomobject]@{ Config = [pscustomobject]@{ Labels = [pscustomobject]@{} } }",
        "[pscustomobject]@{ Config = [pscustomobject]@{} }",
    ),
)
def test_unlabelled_container_has_no_compose_project(container_expression: str):
    result = run_powershell(
        f"$container = {container_expression}; "
        "'project=' + (Get-ContainerComposeProject -Container $container)"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "project="


def test_required_runtime_services_follow_resolved_compose_services():
    result = run_powershell(
        "Select-RequiredRuntimeServices -AvailableServices "
        "@('open-webui','kb-admin-api','kb-admin-dashboard','owui-file-proxy',"
        "'document-worker','caddy-local','academy-provisioner') "
        "| ConvertTo-Json -Compress"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == [
        "open-webui",
        "kb-admin-api",
        "kb-admin-dashboard",
        "owui-file-proxy",
        "document-worker",
        "caddy-local",
    ]


def test_created_rag_service_is_reported_as_unready_after_compose_up():
    result = run_powershell(
        "$services = @("
        "[pscustomobject]@{ Service = 'open-webui'; State = 'running'; Health = 'healthy' },"
        "[pscustomobject]@{ Service = 'kb-admin-api'; State = 'running'; Health = 'healthy' },"
        "[pscustomobject]@{ Service = 'kb-sync'; State = 'created'; Health = '' }"
        "); "
        "Get-UnreadyRequiredServices -Services $services "
        "-RequiredServices @('open-webui','kb-admin-api','kb-sync') "
        "| ConvertTo-Json -Compress"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == "kb-sync (state=created)"


def test_running_service_without_health_field_is_ready():
    result = run_powershell(
        "$services = @("
        "[pscustomobject]@{ Service = 'open-webui'; State = 'running' }"
        "); "
        "@(Get-UnreadyRequiredServices -Services $services "
        "-RequiredServices @('open-webui')).Count"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "0"


def test_multiline_docker_json_is_parsed_as_one_document():
    result = run_powershell(
        "$lines = @('{', '\"services\": {', "
        "'\"open-webui\": {\"container_name\": \"open-webui\"}', '}', '}'); "
        "$config = ConvertFrom-JsonDocument -Lines $lines; "
        "$config.services.'open-webui'.container_name"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "open-webui"
