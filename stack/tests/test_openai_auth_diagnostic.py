"""Temporary diagnostic for sporadic IONOS 401 on vinci-prod-01 (2026-10-23).

The log line must say whether a key was sent and whether it was the configured
one, without ever containing the key itself.
"""

import ast
import json
from pathlib import Path

ROUTER = Path(__file__).resolve().parents[1] / "open-webui-overrides" / "open_webui" / "routers" / "openai.py"


def load_helper():
    tree = ast.parse(ROUTER.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_kahle_auth_diagnostic")
    namespace = {"os": __import__("os"), "json": json}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "openai", "exec"), namespace)
    return namespace["_kahle_auth_diagnostic"]


def test_diagnostic_reports_auth_shape_without_the_key(monkeypatch):
    diagnostic = load_helper()
    secret = "eyJhbGciOiJSUzI1NiJ9.secret-payload.signature"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json", "X-Extra": "1"}
    payload = json.dumps({"model": "m", "messages": [{}, {}], "tools": [{}], "stream": True})

    info = diagnostic(headers, secret, payload, {"task": "title_generation"}, 0)

    text = json.dumps(info)
    assert secret not in text and "secret-payload" not in text
    assert info["auth_header"] is True
    assert info["auth_is_configured_key"] is True
    assert info["key_is_env_key"] is True
    assert info["key_len"] == len(secret)
    assert info["header_names"] == ["Authorization", "Content-Type", "X-Extra"]
    assert info["task"] == "title_generation"
    assert info["messages"] == 2 and info["tools"] == 1 and info["stream"] is True
    assert info["url_idx"] == 0


def test_diagnostic_detects_missing_or_foreign_auth(monkeypatch):
    diagnostic = load_helper()
    monkeypatch.setenv("OPENAI_API_KEY", "configured")

    missing = diagnostic({"Content-Type": "application/json"}, "configured", "{}", None, 1)
    foreign = diagnostic({"Authorization": "Bearer other"}, "configured", "not json", {}, 0)

    assert missing["auth_header"] is False and missing["auth_is_configured_key"] is False
    assert foreign["auth_header"] is True and foreign["auth_is_configured_key"] is False
    assert foreign["messages"] is None


def test_router_logs_the_diagnostic_only_on_auth_failures():
    source = ROUTER.read_text(encoding="utf-8")
    assert "if r.status in (401, 403):" in source
    assert "KAHLE_AUTH_DIAG" in source
