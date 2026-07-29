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
provider_url="$(env_value OPENID_PROVIDER_URL)"
allowed_domains="$(env_value OAUTH_ALLOWED_DOMAINS)"
session_key="$(env_value OAUTH_SESSION_TOKEN_ENCRYPTION_KEY)"
client_info_key="$(env_value OAUTH_CLIENT_INFO_ENCRYPTION_KEY)"

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

expected_provider_url="https://login.microsoftonline.com/${tenant_id}/v2.0/.well-known/openid-configuration"
if [[ "${provider_url}" != "${expected_provider_url}" ]]; then
  echo "ERROR: OPENID_PROVIDER_URL does not match the configured Microsoft tenant." >&2
  exit 1
fi

if [[ ",${allowed_domains}," != *",kahle.de,"* ]]; then
  echo "ERROR: OAUTH_ALLOWED_DOMAINS must include kahle.de." >&2
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

compose=(
  sudo docker compose
  --env-file "${ENV_FILE}"
  -f "${STACK_DIR}/docker-compose.yml"
  -f "${STACK_DIR}/docker-compose.prod.yml"
)

"${compose[@]}" config --quiet

if [[ "${MODE}" == "--check-only" ]]; then
  echo "Production configuration check: OK"
  exit 0
fi

"${compose[@]}" up -d --build --remove-orphans
"${compose[@]}" ps
