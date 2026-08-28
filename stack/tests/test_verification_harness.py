from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-local-tests.ps1"
COMPOSE_CHECK = ROOT / "stack" / "tests" / "compose_static_check.py"


def run_command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def powershell() -> str:
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if not executable:
        pytest.skip("PowerShell is required to exercise the local verification runner")
    return executable


def write_command(path: Path, body: str) -> Path:
    path.write_text("@echo off\r\n" + body.strip() + "\r\n", encoding="utf-8")
    return path


def run_runner(
    tmp_path: Path,
    *,
    tier: str,
    python_body: str,
    npm_body: str,
    node_body: str = "echo fake node %*\r\nexit /b 0",
):
    fake_python = write_command(tmp_path / "python.cmd", python_body)
    fake_npm = write_command(tmp_path / "npm.cmd", npm_body)
    fake_node = write_command(tmp_path / "node.cmd", node_body)
    return run_command(
        powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUNNER),
        "-Tier",
        tier,
        "-Python",
        str(fake_python),
        "-Npm",
        str(fake_npm),
        "-Node",
        str(fake_node),
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def test_compose_check_fails_closed_for_invalid_yaml(tmp_path: Path):
    invalid = tmp_path / "invalid-compose.yml"
    invalid.write_text("services:\n  open-webui: [\n", encoding="utf-8")

    result = run_command(
        sys.executable,
        str(COMPOSE_CHECK),
        "--compose-file",
        str(invalid),
    )

    assert result.returncode == 2
    assert "ERROR:" in combined_output(result)
    assert "passed" not in combined_output(result).lower()


def test_fast_tier_runs_broad_offline_checks_without_full_only_checks(tmp_path: Path):
    result = run_runner(
        tmp_path,
        tier="Fast",
        python_body="echo fake python %*\r\nexit /b 0",
        npm_body="echo fake npm %*\r\nexit /b 0",
    )
    output = combined_output(result)

    assert result.returncode == 0, output
    assert "Compose-Static" in output
    assert "Stack und Sicherheit" in output
    assert "Academy-Provisioner" in output
    assert "Personio-Directory" in output
    assert "Portal-UI-Lint" in output
    assert "Portal-Backend" not in output
    assert "Portal-UI-Build" not in output
    assert "Portal-UI-Renderingtests" not in output


def test_full_tier_runs_every_check_and_collects_independent_failures(tmp_path: Path):
    result = run_runner(
        tmp_path,
        tier="Full",
        python_body=(
            "echo fake python %*\r\n"
            "echo %* | findstr /C:\"compose_static_check.py\" >nul && exit /b 2\r\n"
            "echo %* | findstr /C:\"academy-provisioner\" >nul && exit /b 1\r\n"
            "exit /b 0"
        ),
        npm_body=(
            "echo fake npm %*\r\n"
            "if \"%1\"==\"run\" if \"%2\"==\"build\" exit /b 1\r\n"
            "exit /b 0"
        ),
    )
    output = combined_output(result)

    assert result.returncode == 1, output
    assert "Compose-Static" in output and "TESTFEHLER (Exitcode 2)" in output
    assert "Academy-Provisioner" in output and "TESTFEHLER" in output
    assert "Personio-Directory" in output
    assert "Portal-Backend" in output
    assert "Portal-UI-Lint" in output
    assert "Portal-UI-Build" in output
    assert "Portal-UI-Renderingtests" in output


def test_missing_executable_is_reported_as_setup_error_without_stopping_other_checks(tmp_path: Path):
    fake_npm = write_command(tmp_path / "npm.cmd", "echo fake npm %*\r\nexit /b 0")
    result = run_command(
        powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUNNER),
        "-Tier",
        "Fast",
        "-Python",
        str(tmp_path / "missing-python.exe"),
        "-Npm",
        str(fake_npm),
    )
    output = combined_output(result)

    assert result.returncode == 1, output
    assert "SETUPFEHLER" in output
    assert "Compose-Static" in output
    assert "Personio-Directory" in output
    assert "Portal-UI-Lint" in output


def test_relative_executable_path_is_resolved_before_working_directory_changes(tmp_path: Path):
    fake_python = write_command(tmp_path / "python.cmd", "echo fake python %*\r\nexit /b 0")
    fake_npm = write_command(tmp_path / "npm.cmd", "echo fake npm %*\r\nexit /b 0")
    relative_python = os.path.relpath(fake_python, ROOT)

    result = run_command(
        powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUNNER),
        "-Tier",
        "Fast",
        "-Python",
        relative_python,
        "-Npm",
        str(fake_npm),
    )
    output = combined_output(result)

    assert result.returncode == 0, output
    assert "Stack und Sicherheit" in output
    assert "SETUPFEHLER" not in output


def test_spawn_eperm_is_reported_as_setup_error(tmp_path: Path):
    result = run_runner(
        tmp_path,
        tier="Full",
        python_body="echo fake python %*\r\nexit /b 0",
        npm_body=(
            "echo fake npm %*\r\n"
            "if \"%1\"==\"run\" if \"%2\"==\"build\" echo Error: spawn EPERM && exit /b 1\r\n"
            "exit /b 0"
        ),
    )
    output = combined_output(result)

    assert result.returncode == 1, output
    assert "spawn EPERM" in output
    assert "SETUPFEHLER (Exitcode 1)" in output
    assert "Portal-UI-Build" in output


def test_rendering_tests_run_even_when_ui_build_fails(tmp_path: Path):
    result = run_runner(
        tmp_path,
        tier="Full",
        python_body="echo fake python %*\r\nexit /b 0",
        npm_body=(
            "echo fake npm %*\r\n"
            "if \"%1\"==\"run\" if \"%2\"==\"build\" exit /b 1\r\n"
            "exit /b 0"
        ),
        node_body="echo rendered tests executed\r\nexit /b 0",
    )
    output = combined_output(result)

    assert result.returncode == 1, output
    assert "Portal-UI-Build" in output
    assert "Portal-UI-Renderingtests" in output
    assert "rendered tests executed" in output


def test_missing_pyyaml_is_reported_as_setup_error(tmp_path: Path):
    result = run_runner(
        tmp_path,
        tier="Fast",
        python_body=(
            "echo %* | findstr /C:\"compose_static_check.py\" >nul || exit /b 0\r\n"
            "echo ERROR: PyYAML is required for structured Compose verification.\r\n"
            "exit /b 2"
        ),
        npm_body="echo fake npm %*\r\nexit /b 0",
    )
    output = combined_output(result)

    assert result.returncode == 1, output
    assert "SETUPFEHLER (Exitcode 2)" in output
    assert "Portal-UI-Lint" in output


def test_native_stderr_with_exit_zero_does_not_fail_the_check(tmp_path: Path):
    result = run_runner(
        tmp_path,
        tier="Fast",
        python_body="echo harmless warning 1>&2\r\nexit /b 0",
        npm_body="echo fake npm %*\r\nexit /b 0",
    )

    assert result.returncode == 0, combined_output(result)


def test_native_stderr_with_exit_one_is_classified_by_exit_result(tmp_path: Path):
    result = run_runner(
        tmp_path,
        tier="Fast",
        python_body=(
            "echo %* | findstr /C:\"personio-directory\" >nul || exit /b 0\r\n"
            "echo assertion failed 1>&2\r\n"
            "exit /b 1"
        ),
        npm_body="echo fake npm %*\r\nexit /b 0",
    )
    output = combined_output(result)

    assert result.returncode == 1, output
    assert "TESTFEHLER (Exitcode 1)" in output
    assert "Portal-UI-Lint" in output
