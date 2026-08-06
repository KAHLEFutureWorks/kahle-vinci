#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SOURCE_ENV="${1:-${STACK_DIR}/.env.smoke}"
TARGET_ENV="${2:-${STACK_DIR}/.env.production.pending}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run this script with sudo." >&2
  exit 1
fi

if [[ ! -f "${SOURCE_ENV}" ]]; then
  echo "ERROR: source environment file not found: ${SOURCE_ENV}" >&2
  exit 1
fi

if [[ -e "${TARGET_ENV}" ]]; then
  echo "ERROR: target already exists; refusing to overwrite: ${TARGET_ENV}" >&2
  exit 1
fi

install -o root -g root -m 600 "${SOURCE_ENV}" "${TARGET_ENV}"

cleanup_failed_target() {
  echo "ERROR: preparation failed; removing incomplete target: ${TARGET_ENV}" >&2
  rm -f "${TARGET_ENV}"
}

trap cleanup_failed_target ERR

upsert_env() {
  local name="$1"
  local value="$2"
  local temporary
  temporary="$(mktemp)"

  awk -v key="${name}" -v value="${value}" '
    BEGIN { written = 0 }
    index($0, key "=") == 1 {
      if (!written) {
        print key "=" value
        written = 1
      }
      next
    }
    { print }
    END {
      if (!written) {
        print key "=" value
      }
    }
  ' "${TARGET_ENV}" > "${temporary}"

  install -o root -g root -m 600 "${temporary}" "${TARGET_ENV}"
  rm -f "${temporary}"
}

upsert_env KAHLE_ROOT /opt/kahle-vinci
upsert_env PUBLIC_HOSTNAME vinci.kahle.de
upsert_env WEBUI_URL https://vinci.kahle.de
upsert_env ACME_EMAIL oltmanns@kahle.de

upsert_env OAUTH_ALLOWED_DOMAINS kahle.de
upsert_env OPENID_PROVIDER_URL ""
upsert_env MICROSOFT_CLIENT_ID ""
upsert_env MICROSOFT_CLIENT_SECRET ""
upsert_env MICROSOFT_CLIENT_TENANT_ID ""
upsert_env MICROSOFT_REDIRECT_URI https://vinci.kahle.de/oauth/microsoft/callback
upsert_env MICROSOFT_OAUTH_SCOPE "openid email profile offline_access"
upsert_env DEFAULT_USER_ROLE pending

upsert_env KB_MAIL_TENANT_ID ""
upsert_env KB_MAIL_CLIENT_ID ""
upsert_env KB_MAIL_CLIENT_SECRET ""
upsert_env KB_MAIL_SENDER vinci@kahle.de

upsert_env ENABLE_LOGIN_FORM False
upsert_env ENABLE_PASSWORD_AUTH False

upsert_env OAUTH_SESSION_TOKEN_ENCRYPTION_KEY "$(openssl rand -hex 48)"
upsert_env OAUTH_CLIENT_INFO_ENCRYPTION_KEY "$(openssl rand -hex 48)"

chmod 600 "${TARGET_ENV}"
chown root:root "${TARGET_ENV}"

trap - ERR

echo "Prepared: ${TARGET_ENV}"
echo "Permissions: $(stat -c '%U:%G %a' "${TARGET_ENV}")"
echo "Pending values: OPENID_PROVIDER_URL, MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, MICROSOFT_CLIENT_TENANT_ID, KB_MAIL_TENANT_ID, KB_MAIL_CLIENT_ID, KB_MAIL_CLIENT_SECRET"
echo "No service was restarted and production was not exposed."
