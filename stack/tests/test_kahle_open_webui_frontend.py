from pathlib import Path


STACK = Path(__file__).resolve().parents[1]
PATCH = STACK / "open-webui-custom" / "sidebar-wissensportal.patch"
BRANDING_PATCH = STACK / "open-webui-custom" / "patch_branding.py"
DOCKERFILE = STACK / "open-webui-custom" / "Dockerfile"
COMPOSE = STACK / "docker-compose.kahle-ui.yml"
ROLLOUT = STACK.parent / "deploy" / "activate-kahle-open-webui-wissensportal-20260813.sh"
LOCAL_START = STACK.parent / "scripts" / "start-stack.ps1"


def test_frontend_patch_adds_portal_to_both_sidebar_variants():
    patch = PATCH.read_text(encoding="utf-8")
    assert 'id="sidebar-knowledge-portal-button"' in patch
    assert 'id="sidebar-knowledge-portal-icon-button"' in patch
    assert patch.count('href="/wissen/"') == 2
    assert "BookOpenIcon" in patch


def test_custom_image_is_pinned_to_production_open_webui_revision():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    revision = "f9590b8017199e56d5e953657e6498e3cef1d246"

    assert "FROM ghcr.io/open-webui/open-webui:v0.11.0" in dockerfile
    assert revision in dockerfile
    assert 'test "$(git rev-parse HEAD)" = "${OPEN_WEBUI_REVISION}"' in dockerfile
    assert "image: kahle-open-webui:v0.11.0-kahle.2" in compose
    assert revision in compose


def test_custom_image_uses_exact_kahle_name_and_real_favicon():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    branding_patch = BRANDING_PATCH.read_text(encoding="utf-8")

    assert "WEBUI_NAME: KAHLE-Vinci" in compose
    assert 'ENV WEBUI_NAME="KAHLE-Vinci"' in dockerfile
    assert "public/logo/KAHLE-Vinci-Logo.png /app/build/static/favicon.png" in dockerfile
    assert "public/logo/KAHLE-Vinci-Logo.png /app/build/static/favicon-96x96.png" in dockerfile
    assert "public/logo/KAHLE-Vinci-Logo.png /app/build/static/apple-touch-icon.png" in dockerfile
    assert "WEBUI_NAME += ' (Open WebUI)'" in branding_patch
    assert 'href=\"/static/favicon.png\"' in branding_patch


def test_rollout_checks_running_revision_and_uses_existing_image_switch():
    rollout = ROLLOUT.read_text(encoding="utf-8")
    assert "EXPECTED_BASE_VERSION=\"0.11.0\"" in rollout
    assert "EXPECTED_BASE_REVISION=\"f9590b8017199e56d5e953657e6498e3cef1d246\"" in rollout
    assert "OPEN_WEBUI_IMAGE=${IMAGE}" in rollout
    assert "up -d --no-deps open-webui" in rollout
    assert "grep -R -q 'Wissensportal' /app/build" in rollout
    assert "trap rollback ERR" in rollout
    assert 'cp -a "${BACKUP_ROOT}/.env.production" "${ENV_FILE}"' in rollout


def test_local_start_includes_kahle_ui_overlay():
    script = LOCAL_START.read_text(encoding="utf-8")
    assert '"stack\\docker-compose.kahle-ui.yml"' in script
    assert '@("compose", "-f", $composeFile, "-f", $uiFile)' in script
