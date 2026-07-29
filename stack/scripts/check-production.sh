#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${STACK_DIR}/.env.production}"

compose=(
  sudo docker compose
  --env-file "${ENV_FILE}"
  -f "${STACK_DIR}/docker-compose.yml"
  -f "${STACK_DIR}/docker-compose.prod.yml"
)

"${compose[@]}" config --quiet
"${compose[@]}" ps

echo
echo "Published container ports:"
sudo docker ps --format 'table {{.Names}}\t{{.Ports}}'

echo
echo "Host listeners:"
sudo ss -tulpn
