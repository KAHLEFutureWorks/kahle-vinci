#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${STACK_DIR}/.env.production}"
MODE="${2:-start}"

if [[ "${MODE}" != "start" && "${MODE}" != "--check-only" ]]; then
  echo "ERROR: second argument must be --check-only or omitted." >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: production environment file not found: ${ENV_FILE}" >&2
  exit 1
fi

mode="$(stat -c '%a' "${ENV_FILE}")"
if [[ "${mode}" != "600" && "${mode}" != "400" ]]; then
  echo "ERROR: ${ENV_FILE} must have mode 600 or 400 (current: ${mode})." >&2
  exit 1
fi

required=(
  KAHLE_ROOT PUBLIC_HOSTNAME WEBUI_URL ACME_EMAIL
  OAUTH_ALLOWED_DOMAINS ENABLE_LOGIN_FORM ENABLE_PASSWORD_AUTH
  OPENID_PROVIDER_URL MICROSOFT_CLIENT_ID MICROSOFT_CLIENT_SECRET
  MICROSOFT_CLIENT_TENANT_ID MICROSOFT_REDIRECT_URI
  IONOS_API_KEY WEBUI_SECRET_KEY N8N_BASIC_AUTH_PASSWORD
  N8N_ENCRYPTION_KEY SEARXNG_SECRET_KEY FILE_LINK_SECRET
  OWUI_FILE_PROXY_API_KEY DOC_WORKER_API_KEY
  OAUTH_SESSION_TOKEN_ENCRYPTION_KEY OAUTH_CLIENT_INFO_ENCRYPTION_KEY
  KB_ADMIN_UNLOCK_CODE_HASH KB_ADMIN_UNLOCK_SESSION_SECRET
  PORTAL_ALLOWED_EMAIL_DOMAINS
)

for name in "${required[@]}"; do
  if ! grep -Eq "^${name}=.+" "${ENV_FILE}"; then
    echo "ERROR: required value ${name} is missing or empty in ${ENV_FILE}." >&2
    exit 1
  fi
done

env_value() {
  local name="$1"
  sed -n "s/^${name}=//p" "${ENV_FILE}" | tail -n 1
}

if grep -Eq '(<[^>]+>|example\.com|changeme)' "${ENV_FILE}"; then
  echo "ERROR: placeholder values remain in ${ENV_FILE}." >&2
  exit 1
fi

root_dir="$(sed -n 's/^KAHLE_ROOT=//p' "${ENV_FILE}" | tail -n 1)"
if [[ -z "${root_dir}" || "${root_dir}" != /* ]]; then
  echo "ERROR: KAHLE_ROOT must be an absolute Linux path." >&2
  exit 1
fi

public_hostname="$(env_value PUBLIC_HOSTNAME)"
webui_url="$(env_value WEBUI_URL)"
redirect_uri="$(env_value MICROSOFT_REDIRECT_URI)"
tenant_id="$(env_value MICROSOFT_CLIENT_TENANT_ID)"
client_id="$(env_value MICROSOFT_CLIENT_ID)"
client_secret="$(env_value MICROSOFT_CLIENT_SECRET)"
provider_url="$(env_value OPENID_PROVIDER_URL)"
allowed_domains="$(env_value OAUTH_ALLOWED_DOMAINS)"
session_key="$(env_value OAUTH_SESSION_TOKEN_ENCRYPTION_KEY)"
client_info_key="$(env_value OAUTH_CLIENT_INFO_ENCRYPTION_KEY)"
mail_tenant_id="$(env_value KB_MAIL_TENANT_ID)"
mail_client_id="$(env_value KB_MAIL_CLIENT_ID)"
mail_client_secret="$(env_value KB_MAIL_CLIENT_SECRET)"
mail_sender="$(env_value KB_MAIL_SENDER)"
portal_allowed_domains="$(env_value PORTAL_ALLOWED_EMAIL_DOMAINS)"

# Portal mail and Outlook absence sync use the existing Vinci Graph app by
# default. KB_MAIL_* remains available only as an explicit credential override.
mail_tenant_id="${mail_tenant_id:-${tenant_id}}"
mail_client_id="${mail_client_id:-${client_id}}"
mail_client_secret="${mail_client_secret:-${client_secret}}"

if [[ "${public_hostname}" != "vinci.kahle.de" || "${webui_url}" != "https://vinci.kahle.de" ]]; then
  echo "ERROR: production identity must be vinci.kahle.de over HTTPS." >&2
  exit 1
fi

if [[ "${redirect_uri}" != "${webui_url}/oauth/microsoft/callback" ]]; then
  echo "ERROR: MICROSOFT_REDIRECT_URI must exactly match ${webui_url}/oauth/microsoft/callback." >&2
  exit 1
fi

uuid_pattern='^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$'
if [[ ! "${tenant_id}" =~ ${uuid_pattern} ]]; then
  echo "ERROR: MICROSOFT_CLIENT_TENANT_ID is not a valid UUID." >&2
  exit 1
fi

if [[ ! "${client_id}" =~ ${uuid_pattern} ]]; then
  echo "ERROR: MICROSOFT_CLIENT_ID is not a valid UUID." >&2
  exit 1
fi
if [[ -n "${mail_sender}" ]]; then
  if [[ ! "${mail_tenant_id}" =~ ${uuid_pattern} || ! "${mail_client_id}" =~ ${uuid_pattern} ]]; then
    echo "ERROR: Microsoft Graph mail tenant and client IDs must be valid UUIDs." >&2
    exit 1
  fi
  if [[ ! "${mail_sender}" =~ ^[A-Za-z0-9._%+-]+@kahle\.de$ ]]; then
    echo "ERROR: KB_MAIL_SENDER must be a kahle.de mailbox." >&2
    exit 1
  fi
fi

expected_provider_url="https://login.microsoftonline.com/${tenant_id}/v2.0/.well-known/openid-configuration"
if [[ "${provider_url}" != "${expected_provider_url}" ]]; then
  echo "ERROR: OPENID_PROVIDER_URL does not match the configured Microsoft tenant." >&2
  exit 1
fi

if [[ ",${allowed_domains}," != *",kahle.de,"* ]]; then
  echo "ERROR: OAUTH_ALLOWED_DOMAINS must include kahle.de." >&2
  exit 1
fi

if [[ ",${portal_allowed_domains}," != *",kahle.de,"* ]]; then
  echo "ERROR: PORTAL_ALLOWED_EMAIL_DOMAINS must include kahle.de." >&2
  exit 1
fi

if [[ "$(env_value ENABLE_LOGIN_FORM)" != "False" || "$(env_value ENABLE_PASSWORD_AUTH)" != "False" ]]; then
  echo "ERROR: production must use Microsoft SSO only; local login and password auth must be False." >&2
  exit 1
fi

if (( ${#session_key} < 64 || ${#client_info_key} < 64 )); then
  echo "ERROR: OAuth encryption keys must each contain at least 64 characters." >&2
  exit 1
fi

if [[ "${session_key}" == "${client_info_key}" ]]; then
  echo "ERROR: OAuth session and client-info encryption keys must be different." >&2
  exit 1
fi

mkdir -p \
  "${root_dir}/knowledgebases" \
  "${root_dir}/kb-sync-state" \
  "${root_dir}/n8n" \
  "${root_dir}/searxng" \
  "${root_dir}/stack/retention-reports"

portal_uid="$(env_value KB_ADMIN_UID)"
portal_gid="$(env_value KB_ADMIN_GID)"
portal_uid="${portal_uid:-1000}"
portal_gid="${portal_gid:-1000}"
install -d -o "${portal_uid}" -g "${portal_gid}" -m 750 \
  "${root_dir}/kb-portal-data" \
  "${root_dir}/kb-portal-data/files"

compose=(
  sudo docker compose
  --env-file "${ENV_FILE}"
  -f "${STACK_DIR}/docker-compose.yml"
  -f "${STACK_DIR}/docker-compose.prod.yml"
)

if [[ "$(env_value ENABLE_PORTAL_BACKUP_WORKER)" == "True" ]]; then
  backup_secondary_root="$(env_value KAHLE_BACKUP_SECONDARY_ROOT)"
  if [[ -z "$(env_value KB_BACKUP_ENCRYPTION_KEY)" ]]; then
    echo "ERROR: KB_BACKUP_ENCRYPTION_KEY is required when ENABLE_PORTAL_BACKUP_WORKER=True." >&2
    exit 1
  fi
  if [[ -z "${backup_secondary_root}" || "${backup_secondary_root}" != /* ]]; then
    echo "ERROR: KAHLE_BACKUP_SECONDARY_ROOT must be an absolute Linux path when the portal backup worker is enabled." >&2
    exit 1
  fi
  compose+=(--profile operations)
fi

"${compose[@]}" config --quiet

if [[ "${MODE}" == "--check-only" ]]; then
  echo "Production configuration check: OK"
  exit 0
fi

"${compose[@]}" up -d --build --remove-orphans
"${compose[@]}" ps
