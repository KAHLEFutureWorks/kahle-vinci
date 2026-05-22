#!/usr/bin/env python3
"""Static contract tests for the KAHLE OpenWebUI branding layer."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BRANDING_ROOT = ROOT / "stack" / "open-webui-kahle"


def load_patch_module():
    path = BRANDING_ROOT / "patch_openwebui.py"
    spec = importlib.util.spec_from_file_location("patch_openwebui", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dockerfile_copies_brand_assets():
    text = (BRANDING_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ghcr.io/open-webui/open-webui:v0.9.2" in text
    assert "public/logo/KAHLE-Vinci-Logo.png /app/build/static/kahle/logo.png" in text
    assert "public/background/Logo_Kahle_Gruppe_positiv.jpg /app/build/static/kahle/chat-background.jpg" in text
    assert "patch_openwebui.py" in text


def test_branding_js_contains_access_contract():
    text = (BRANDING_ROOT / "static" / "kahle-branding.js").read_text(encoding="utf-8")
    assert 'const BRAND_NAME = "KAHLE-Vinci"' in text
    assert '"geschaeftsleitung"' in text
    assert '"geschaftsleitung"' in text
    assert '"ai-pilot"' in text
    assert "normalizeLabel" in text
    assert "ensureBackgroundLayer" in text
    assert "findSettingsRow" in text
    assert 'user?.role === "admin"' in text
    assert '"/api/v1/auths/"' in text
    assert '"/api/v1/groups/"' in text
    assert '"benutzeroberflache"' in text
    assert '"verbindungen"' in text
    assert '"integrationen"' in text
    assert '"datenkontrolle"' in text
    assert '"advanced parameters"' in text


def test_branding_css_contains_background_contract():
    text = (BRANDING_ROOT / "static" / "kahle-branding.css").read_text(encoding="utf-8")
    assert '--kahle-chat-background: url("/static/kahle/chat-background.jpg")' in text
    assert "#kahle-chat-background-layer" in text
    assert "body.kahle-branding-ready > *" not in text
    assert "data-kahle-chat-transparent" in text
    assert "kahle-hide-advanced-settings" in text
    assert "data-kahle-hidden" in text


def test_patch_script_is_idempotent_for_index_and_env():
    module = load_patch_module()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        index = tmp_path / "index.html"
        env = tmp_path / "env.py"
        index.write_text(
            """<!doctype html>
<html>
  <head>
\t\t<script src="/static/loader.js" defer crossorigin="use-credentials"></script>
\t\t<link rel="stylesheet" href="/static/custom.css" crossorigin="use-credentials" />
  </head>
</html>
""",
            encoding="utf-8",
        )
        env.write_text(
            """import os
WEBUI_NAME = os.environ.get('WEBUI_NAME', 'Open WebUI')
if WEBUI_NAME != 'Open WebUI':
    WEBUI_NAME += ' (Open WebUI)'
""",
            encoding="utf-8",
        )

        module.patch_index(index)
        module.patch_index(index)
        module.patch_env(env)
        module.patch_env(env)

        index_text = index.read_text(encoding="utf-8")
        env_text = env.read_text(encoding="utf-8")
        assert index_text.count("/static/kahle/kahle-branding.js") == 1
        assert index_text.count("/static/kahle/kahle-branding.css") == 1
        assert "WEBUI_NAME += ' (Open WebUI)'" not in env_text
        assert env_text.count("WEBUI_NAME = os.environ.get('WEBUI_NAME', 'Open WebUI')") == 1


if __name__ == "__main__":
    test_dockerfile_copies_brand_assets()
    test_branding_js_contains_access_contract()
    test_branding_css_contains_background_contract()
    test_patch_script_is_idempotent_for_index_and_env()
    print("open webui KAHLE branding tests passed")
