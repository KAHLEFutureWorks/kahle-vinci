from pathlib import Path


STACK_DIR = Path(__file__).resolve().parents[1]
BASE_COMPOSE = (STACK_DIR / "docker-compose.yml").read_text(encoding="utf-8")
PROD_COMPOSE = (STACK_DIR / "docker-compose.prod.yml").read_text(encoding="utf-8")
PREPARE_SCRIPT = (STACK_DIR / "scripts" / "prepare-production-env.sh").read_text(
    encoding="utf-8"
)
START_SCRIPT = (STACK_DIR / "scripts" / "start-production.sh").read_text(
    encoding="utf-8"
)
BOOTSTRAP_COMPOSE = (
    STACK_DIR / "docker-compose.oauth-bootstrap.yml"
).read_text(encoding="utf-8")
BOOTSTRAP_CADDY = (STACK_DIR / "caddy" / "Caddyfile.bootstrap").read_text(
    encoding="utf-8"
)
BOOTSTRAP_SCRIPT = (
    STACK_DIR / "scripts" / "start-oauth-bootstrap.sh"
).read_text(encoding="utf-8")
CADDYFILE = (STACK_DIR / "caddy" / "Caddyfile").read_text(encoding="utf-8")



def test_open_webui_is_sso_only_and_uses_secure_oauth_cookies():
    required = (
        'ENABLE_LOGIN_FORM: ${ENABLE_LOGIN_FORM:-False}',
        'ENABLE_PASSWORD_AUTH: ${ENABLE_PASSWORD_AUTH:-False}',
        'ENABLE_PASSWORD_CHANGE_FORM: "False"',
        'OAUTH_AUTO_REDIRECT: "True"',
        'WEBUI_SESSION_COOKIE_SECURE: "True"',
        'WEBUI_AUTH_COOKIE_SECURE: "True"',
        'WEBUI_SESSION_COOKIE_SAME_SITE: "none"',
        'WEBUI_AUTH_COOKIE_SAME_SITE: "none"',
        'OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "False"',
        'CORS_ALLOW_ORIGIN: ${WEBUI_URL:?WEBUI_URL is required}',
    )
    for value in required:
        assert value in PROD_COMPOSE


def test_open_webui_requires_provider_and_persistent_encryption_keys():
    required = (
        "OPENID_PROVIDER_URL",
        "MICROSOFT_CLIENT_ID",
        "MICROSOFT_CLIENT_SECRET",
        "MICROSOFT_CLIENT_TENANT_ID",
        "MICROSOFT_REDIRECT_URI",
        "OAUTH_SESSION_TOKEN_ENCRYPTION_KEY",
        "OAUTH_CLIENT_INFO_ENCRYPTION_KEY",
    )
    for name in required:
        assert f"{name}: ${{{name}:?" in PROD_COMPOSE
        assert name in START_SCRIPT


def test_pending_environment_is_private_and_does_not_start_services():
    assert ".env.production.pending" in PREPARE_SCRIPT
    assert 'install -o root -g root -m 600' in PREPARE_SCRIPT
    assert "chmod 600" in PREPARE_SCRIPT
    assert "chown root:root" in PREPARE_SCRIPT
    assert "docker compose" not in PREPARE_SCRIPT
    assert "systemctl" not in PREPARE_SCRIPT


def test_pending_environment_has_fixed_public_identity_and_empty_entra_values():
    required = (
        "upsert_env PUBLIC_HOSTNAME vinci.kahle.de",
        "upsert_env WEBUI_URL https://vinci.kahle.de",
        "upsert_env OAUTH_ALLOWED_DOMAINS kahle.de",
        "upsert_env MICROSOFT_REDIRECT_URI https://vinci.kahle.de/oauth/microsoft/callback",
        'upsert_env MICROSOFT_OAUTH_SCOPE "openid email profile offline_access"',
        'upsert_env OPENID_PROVIDER_URL ""',
        'upsert_env MICROSOFT_CLIENT_ID ""',
        'upsert_env MICROSOFT_CLIENT_SECRET ""',
        'upsert_env MICROSOFT_CLIENT_TENANT_ID ""',
        "upsert_env ENABLE_LOGIN_FORM False",
        "upsert_env ENABLE_PASSWORD_AUTH False",
    )
    for value in required:
        assert value in PREPARE_SCRIPT


def test_oauth_encryption_keys_are_generated_independently():
    assert PREPARE_SCRIPT.count('"$(openssl rand -hex 48)"') == 2


def test_production_start_validates_exact_entra_and_sso_configuration():
    required = (
        'public_hostname}" != "vinci.kahle.de',
        'webui_url}" != "https://vinci.kahle.de',
        '${webui_url}/oauth/microsoft/callback',
        'https://login.microsoftonline.com/${tenant_id}/v2.0/.well-known/openid-configuration',
        'MICROSOFT_CLIENT_TENANT_ID is not a valid UUID',
        'MICROSOFT_CLIENT_ID is not a valid UUID',
        'env_value ENABLE_LOGIN_FORM)" != "False"',
        'env_value ENABLE_PASSWORD_AUTH)" != "False"',
        '${#session_key} < 64',
        '${#client_info_key} < 64',
        'session_key}" == "${client_info_key}',
    )
    for value in required:
        assert value in START_SCRIPT

def test_normal_production_keeps_email_merge_disabled():
    assert 'OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "False"' in PROD_COMPOSE
    assert 'OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "True"' not in PROD_COMPOSE


def test_bootstrap_is_explicit_one_time_email_merge_override():
    assert 'OAUTH_MERGE_ACCOUNTS_BY_EMAIL: "True"' in BOOTSTRAP_COMPOSE
    assert "Caddyfile.bootstrap:/etc/caddy/Caddyfile:ro" in BOOTSTRAP_COMPOSE
    assert "BOOTSTRAP_ALLOWED_IP" in BOOTSTRAP_COMPOSE


def test_bootstrap_caddy_keeps_health_public_and_app_ip_restricted():
    assert "@health path /healthz" in BOOTSTRAP_CADDY
    assert 'respond "ok" 200' in BOOTSTRAP_CADDY
    assert "@bootstrap_client remote_ip {$BOOTSTRAP_ALLOWED_IP}" in BOOTSTRAP_CADDY
    assert "handle @bootstrap_client" in BOOTSTRAP_CADDY
    assert "reverse_proxy open-webui:8080" in BOOTSTRAP_CADDY
    assert 'respond "KAHLE-Vinci ist noch nicht freigeschaltet." 503' in BOOTSTRAP_CADDY


def test_bootstrap_script_requires_one_public_ipv4_and_preflights_production():
    assert "second argument must be one public IPv4 /32 CIDR" in BOOTSTRAP_SCRIPT
    assert "must be a public IPv4 address" in BOOTSTRAP_SCRIPT
    assert "ipaddress.ip_network" in BOOTSTRAP_SCRIPT
    assert "network.network_address.is_global" in BOOTSTRAP_SCRIPT
    assert '"${SCRIPT_DIR}/start-production.sh" "${ENV_FILE}" --check-only' in BOOTSTRAP_SCRIPT
    assert "docker-compose.oauth-bootstrap.yml" in BOOTSTRAP_SCRIPT
    assert "export BOOTSTRAP_ALLOWED_IP" in BOOTSTRAP_SCRIPT


def test_production_start_supports_non_mutating_check_only_mode():
    assert 'MODE="${2:-start}"' in START_SCRIPT
    assert 'if [[ "${MODE}" == "--check-only" ]]' in START_SCRIPT
    check_position = START_SCRIPT.index('if [[ "${MODE}" == "--check-only" ]]')
    start_position = START_SCRIPT.index('"${compose[@]}" up -d')
    assert check_position < start_position

def test_vector_dashboard_second_gate_is_required_in_production():
    assert "KB_ADMIN_UNLOCK_CODE_HASH" in BASE_COMPOSE
    assert "KB_ADMIN_UNLOCK_SESSION_SECRET" in BASE_COMPOSE
    assert "KB_ADMIN_UNLOCK_CODE_HASH is required" in PROD_COMPOSE
    assert "KB_ADMIN_UNLOCK_SESSION_SECRET is required" in PROD_COMPOSE
    configure_script = (STACK_DIR / "scripts" / "configure-kb-admin-unlock.py").read_text(
        encoding="utf-8"
    )
    assert "getpass.getpass" in configure_script
    assert "pbkdf2_hmac" in configure_script
    assert "KB_ADMIN_UNLOCK_SESSION_SECRET" in configure_script

def test_vector_dashboard_static_and_page_routes_require_admin_session():
    assert CADDYFILE.count("forward_auth kb-admin-api:8092") == 2
    assert CADDYFILE.count("uri /portal/session") == 2
    static_position = CADDYFILE.index("handle @vector_static")
    page_position = CADDYFILE.index("handle /wissen/*")
    assert CADDYFILE.index("forward_auth kb-admin-api:8092", static_position) < page_position
    assert CADDYFILE.index("forward_auth kb-admin-api:8092", page_position) > page_position


def test_sharepoint_embedding_is_narrow_and_sensitive_routes_remain_blocked():
    assert "Content-Security-Policy \"frame-ancestors 'self' https://kahlekg.sharepoint.com\"" in CADDYFILE
    assert "-X-Frame-Options" in CADDYFILE
    assert CADDYFILE.count("Content-Security-Policy \"frame-ancestors 'none'\"") == 4
    assert CADDYFILE.count('X-Frame-Options "DENY"') == 4
    for route in (
        "handle /files/*",
        "handle_path /wissen/api/*",
        "handle @vector_static",
        "handle /wissen/*",
    ):
        route_position = CADDYFILE.index(route)
        next_handle = CADDYFILE.find("\n\thandle", route_position + len(route))
        route_block = CADDYFILE[route_position : next_handle if next_handle != -1 else len(CADDYFILE)]
        assert "frame-ancestors 'none'" in route_block
        assert 'X-Frame-Options "DENY"' in route_block


def test_sharepoint_embedding_uses_cross_site_secure_oauth_cookies():
    """OAuth state and auth cookies must survive the SharePoint iframe boundary."""
    assert 'WEBUI_SESSION_COOKIE_SAME_SITE: "none"' in PROD_COMPOSE
    assert 'WEBUI_AUTH_COOKIE_SAME_SITE: "none"' in PROD_COMPOSE
    assert 'WEBUI_SESSION_COOKIE_SECURE: "True"' in PROD_COMPOSE
    assert 'WEBUI_AUTH_COOKIE_SECURE: "True"' in PROD_COMPOSE

def test_production_requires_microsoft_graph_mail_delivery_configuration():
    env_example = (STACK_DIR / ".env.example").read_text(encoding="utf-8")
    production_template = (STACK_DIR / "env.production.template").read_text(encoding="utf-8")
    required = ("KB_MAIL_TENANT_ID", "KB_MAIL_CLIENT_ID", "KB_MAIL_CLIENT_SECRET", "KB_MAIL_SENDER")
    for name in required:
        assert f"{name}: ${{{name}:?" in PROD_COMPOSE
        assert name in START_SCRIPT
        assert name in PREPARE_SCRIPT
        assert name in env_example
        assert name in production_template
    assert "Microsoft Graph mail tenant and client IDs must be valid UUIDs" in START_SCRIPT
    assert "KB_MAIL_SENDER must be a kahle.de mailbox" in START_SCRIPT
