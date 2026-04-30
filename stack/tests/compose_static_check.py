#!/usr/bin/env python3
"""Static checks for the local docker-compose contract."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any


SECRET_NAME_RE = re.compile(r"(api[_-]?key|token|secret|password|credential)", re.IGNORECASE)
SECRET_VALUE_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|[A-Za-z0-9_/-]{32,})"
)


def load_yaml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        import yaml  # type: ignore
    except Exception:
        return None, "PyYAML not installed; using text checks only."

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive reporting
        return None, f"Could not parse YAML: {exc}"

    if not isinstance(loaded, dict):
        return None, "Compose file did not parse as a mapping."
    return loaded, None


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def iter_environment(env: Any) -> list[tuple[str, str]]:
    if isinstance(env, dict):
        return [(str(k), "" if v is None else str(v)) for k, v in env.items()]
    if isinstance(env, list):
        pairs: list[tuple[str, str]] = []
        for item in env:
            text = str(item)
            if "=" in text:
                key, value = text.split("=", 1)
            else:
                key, value = text, ""
            pairs.append((key, value))
        return pairs
    return []


def image_uses_forbidden_tag(image: str) -> bool:
    return image.endswith(":latest") or image.endswith(":main") or ":latest@" in image or ":main@" in image


def port_is_localhost_only(port: Any) -> bool:
    if isinstance(port, dict):
        host_ip = str(port.get("host_ip") or port.get("host_ip".replace("_", "")) or "")
        published = port.get("published")
        if not published:
            return True
        return host_ip == "127.0.0.1"

    text = str(port).strip().strip('"').strip("'")
    if not text:
        return True
    if text.startswith("127.0.0.1:"):
        return True
    if re.match(r"^\d+(/\w+)?$", text):
        return False
    if re.match(r"^\d+:\d+", text):
        return False
    if text.startswith("0.0.0.0:") or text.startswith("[::]:"):
        return False
    return False


def looks_like_direct_secret(key: str, value: str) -> bool:
    if not value or value.startswith("${"):
        return False
    if not SECRET_NAME_RE.search(key):
        return False
    lower = value.lower()
    if lower in {"true", "false", "none", "null", "changeme", "example"}:
        return False
    return bool(SECRET_VALUE_RE.search(value) or len(value) >= 12)


def yaml_checks(compose: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    services = compose.get("services") or {}
    if not isinstance(services, dict):
        return ["services must be a mapping"]

    for forbidden in ("ollama", "kunden-sql-gateway"):
        if forbidden in services:
            failures.append(f"forbidden service present: {forbidden}")

    for service_name, service in services.items():
        if not isinstance(service, dict):
            continue

        image = str(service.get("image") or "")
        if image and image_uses_forbidden_tag(image):
            failures.append(f"{service_name}: image must not use :latest or :main ({image})")

        for port in as_list(service.get("ports")):
            if not port_is_localhost_only(port):
                failures.append(f"{service_name}: published port must bind 127.0.0.1 only ({port})")

        for env_file in as_list(service.get("env_file")):
            env_text = str(env_file).replace("\\", "/").strip()
            if env_text in {".env", "./.env", "stack/.env", "./stack/.env"} or env_text.endswith("/stack/.env"):
                failures.append(f"{service_name}: must not reference stack/.env via env_file ({env_file})")

        for key, value in iter_environment(service.get("environment")):
            if looks_like_direct_secret(key, value):
                failures.append(f"{service_name}: possible direct secret in environment key {key}")

    return failures


def text_checks(text: str) -> list[str]:
    failures: list[str] = []
    lowered = text.lower()

    for forbidden in ("ollama", "kunden-sql-gateway"):
        if re.search(rf"^\s{{2}}{re.escape(forbidden)}\s*:", text, re.MULTILINE):
            failures.append(f"forbidden service present: {forbidden}")

    for match in re.finditer(r"image\s*:\s*['\"]?([^'\"\s]+)", text):
        image = match.group(1)
        if image_uses_forbidden_tag(image):
            failures.append(f"image must not use :latest or :main ({image})")

    for match in re.finditer(r"^\s*-\s*['\"]?([^'\"\n]*:\d+(?:/\w+)?)['\"]?\s*$", text, re.MULTILINE):
        port = match.group(1)
        if re.search(r"^\d+:\d+", port) or port.startswith("0.0.0.0:") or port.startswith("[::]:"):
            failures.append(f"published port must bind 127.0.0.1 only ({port})")

    if re.search(r"env_file\s*:\s*\n\s*-\s*\.env\b", text) or "stack/.env" in lowered:
        failures.append("must not reference stack/.env via env_file")

    for match in re.finditer(r"^\s*[- ]\s*([A-Za-z0-9_]*?(?:KEY|TOKEN|SECRET|PASSWORD)[A-Za-z0-9_]*)\s*[:=]\s*([^\n#]+)", text):
        key, value = match.group(1), match.group(2).strip().strip('"').strip("'")
        if looks_like_direct_secret(key, value):
            failures.append(f"possible direct secret in environment key {key}")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Static checks for stack/docker-compose.yml")
    parser.add_argument("--compose-file", default="stack/docker-compose.yml")
    args = parser.parse_args()

    compose_path = Path(args.compose_file)
    if not compose_path.exists():
        print(f"ERROR: compose file not found: {compose_path}", file=sys.stderr)
        return 2

    text = compose_path.read_text(encoding="utf-8")
    compose, warning = load_yaml(compose_path)
    failures = yaml_checks(compose) if compose is not None else text_checks(text)

    if warning:
        print(f"NOTE: {warning}")

    if failures:
        print("Compose static check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Compose static check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
