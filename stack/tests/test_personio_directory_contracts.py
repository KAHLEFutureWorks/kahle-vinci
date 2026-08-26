import json
import os
import re
import subprocess
from pathlib import Path


STACK_ROOT = Path(__file__).resolve().parents[1]


def _service_block(compose: str, service: str) -> str:
    match = re.search(rf"(?m)^  {re.escape(service)}:\s*$", compose)
    assert match is not None
    start = match.start()
    next_service = re.search(r"\n  [a-zA-Z0-9_-]+:\n", compose[start + 1 :])
    return compose[start:] if next_service is None else compose[start : start + 1 + next_service.start()]


def _rendered_compose(*, harness_mode: str | None = None) -> dict:
    compose_paths = [STACK_ROOT / "docker-compose.yml", STACK_ROOT / "docker-compose.prod.yml"]
    source = "\n".join(path.read_text(encoding="utf-8") for path in compose_paths)
    required_names = set(re.findall(r"\$\{([A-Z0-9_]+):\?", source))
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP")
        if key in os.environ
    }
    env.update({name: "contract-test" for name in required_names})
    env["KAHLE_ROOT"] = str(STACK_ROOT.parent)
    env["LEARNINGSUITE_ALLOWED_EMAILS"] = "contract-test@kahle.invalid"
    if harness_mode is not None:
        env["KAHLE_KNOWLEDGE_HARNESS_MODE"] = harness_mode
    completed = subprocess.run(
        [
            "docker-compose",
            "-f",
            str(compose_paths[0]),
            "-f",
            str(compose_paths[1]),
            "config",
            "--format",
            "json",
        ],
        cwd=STACK_ROOT.parent,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_personio_directory_compose_is_internal_and_hardened() -> None:
    compose = (STACK_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    block = _service_block(compose, "personio-directory")
    assert "ports:" not in block
    assert 'expose:\n      - "8094"' in block
    assert "read_only: true" in block
    assert "- no-new-privileges:true" in block
    assert "cap_drop:\n      - ALL" in block
    assert "personio_directory_state:/state" in block
    assert "healthcheck:" in block
    assert "networks:\n      - appnet" in block


def test_personio_credentials_are_only_in_directory_service() -> None:
    compose = (STACK_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    directory = _service_block(compose, "personio-directory")
    open_webui = _service_block(compose, "open-webui")
    assert "PERSONIO_CLIENT_ID: ${PERSONIO_CLIENT_ID:?PERSONIO_CLIENT_ID is required}" in directory
    assert "PERSONIO_API: ${PERSONIO_API:?PERSONIO_API is required}" in directory
    assert "PERSONIO_CLIENT_ID" not in open_webui
    assert "PERSONIO_API" not in open_webui
    assert "PERSONIO_DIRECTORY_URL: http://personio-directory:8094" in open_webui
    assert "PERSONIO_DIRECTORY_API_KEY:" in open_webui
    assert (
        "personio_directory_client.py:/app/backend/open_webui/utils/"
        "personio_directory_client.py:ro"
    ) in open_webui
    assert "personio-directory:\n        condition: service_started" in open_webui


def test_rendered_standard_and_production_compose_activate_harness_without_health_coupling() -> None:
    rendered = _rendered_compose()
    open_webui = rendered["services"]["open-webui"]

    assert open_webui["environment"]["KAHLE_KNOWLEDGE_HARNESS_MODE"] == "active"
    assert open_webui["depends_on"]["personio-directory"]["condition"] == "service_started"


def test_rendered_compose_preserves_explicit_harness_off_switch() -> None:
    rendered = _rendered_compose(harness_mode="off")

    assert (
        rendered["services"]["open-webui"]["environment"][
            "KAHLE_KNOWLEDGE_HARNESS_MODE"
        ]
        == "off"
    )


def test_personio_directory_production_resources_and_template() -> None:
    prod = (STACK_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    prod_block = _service_block(prod, "personio-directory")
    template = (STACK_ROOT / "env.production.template").read_text(encoding="utf-8")
    assert "mem_limit: 512m" in prod_block
    assert "cpus: 1.0" in prod_block
    assert "pids_limit: 128" in prod_block
    assert "PERSONIO_CLIENT_ID=<client-id>" in template
    assert "PERSONIO_API=<secret>" in template


def test_local_start_imports_personio_user_variables_without_persisting_values() -> None:
    script = (STACK_ROOT.parent / "scripts" / "start-stack.ps1").read_text(
        encoding="utf-8"
    )

    assert '"PERSONIO_CLIENT_ID"' in script
    assert '"PERSONIO_API"' in script
    assert 'GetEnvironmentVariable($name, "User")' in script
    assert 'Set-Item -Path "Env:$name" -Value $userValue' in script
    assert 'Remove-Item -Path "Env:$name"' in script
