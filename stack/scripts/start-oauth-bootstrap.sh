#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${STACK_DIR}/.env.production}"
BOOTSTRAP_ALLOWED_IP="${2:-}"

if [[ ! "${BOOTSTRAP_ALLOWED_IP}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/32$ ]]; then
  echo "ERROR: second argument must be one public IPv4 /32 CIDR." >&2
  exit 1
fi

if ! python3 -c 'import ipaddress, sys; network = ipaddress.ip_network(sys.argv[1], strict=True); assert network.version == 4 and network.prefixlen == 32 and network.network_address.is_global' "${BOOTSTRAP_ALLOWED_IP}" 2>/dev/null; then
  echo "ERROR: BOOTSTRAP_ALLOWED_IP must be one globally routable IPv4 /32 CIDR." >&2
  exit 1
fi

IFS=. read -r octet1 octet2 octet3 octet4_with_prefix <<< "${BOOTSTRAP_ALLOWED_IP}"
octet4="${octet4_with_prefix%/32}"
for octet in "${octet1}" "${octet2}" "${octet3}" "${octet4}"; do
  if (( 10#${octet} > 255 )); then
    echo "ERROR: invalid IPv4 address: ${BOOTSTRAP_ALLOWED_IP}" >&2
    exit 1
  fi
done

case "${BOOTSTRAP_ALLOWED_IP}" in
  10.*|127.*|169.254.*|192.168.*|0.*)
    echo "ERROR: BOOTSTRAP_ALLOWED_IP must be a public IPv4 address." >&2
    exit 1
    ;;
esac

if [[ "${octet1}" == "172" ]] && (( octet2 >= 16 && octet2 <= 31 )); then
  echo "ERROR: BOOTSTRAP_ALLOWED_IP must not be an RFC1918 address." >&2
  exit 1
fi

"${SCRIPT_DIR}/start-production.sh" "${ENV_FILE}" --check-only

export BOOTSTRAP_ALLOWED_IP

compose=(
  sudo docker compose
  --env-file "${ENV_FILE}"
  -f "${STACK_DIR}/docker-compose.yml"
  -f "${STACK_DIR}/docker-compose.prod.yml"
  -f "${STACK_DIR}/docker-compose.oauth-bootstrap.yml"
)

"${compose[@]}" config --quiet
"${compose[@]}" up -d --build --remove-orphans
"${compose[@]}" ps

echo
echo "OAuth bootstrap is active only for ${BOOTSTRAP_ALLOWED_IP}."
echo "Complete the admin Microsoft login, verify the preserved user ID, then immediately run start-production.sh."