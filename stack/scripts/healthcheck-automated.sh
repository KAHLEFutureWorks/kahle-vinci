#!/usr/bin/env bash
set -Eeuo pipefail

STATUS_DIR="${STATUS_DIR:-/var/lib/kahle-vinci-monitor}"
BACKUP_STATUS_DIR="${BACKUP_STATUS_DIR:-/var/lib/kahle-vinci-backup}"
MAX_BACKUP_AGE_HOURS="${MAX_BACKUP_AGE_HOURS:-36}"
MAX_DISK_PERCENT="${MAX_DISK_PERCENT:-85}"
MAX_INODE_PERCENT="${MAX_INODE_PERCENT:-85}"
PUBLIC_EDGE_HEALTH_URL="${PUBLIC_EDGE_HEALTH_URL:-https://vinci.kahle.de/healthz}"

failures=()

fail() {
  failures+=("$1")
}

if (( EUID != 0 )); then
  echo "FEHLER: Dieses Skript muss als root laufen." >&2
  exit 1
fi

for value_name in MAX_BACKUP_AGE_HOURS MAX_DISK_PERCENT MAX_INODE_PERCENT; do
  value="${!value_name}"
  if ! [[ "$value" =~ ^[0-9]+$ ]] || (( value < 1 || value > 100 )); then
    echo "FEHLER: $value_name muss eine ganze Zahl zwischen 1 und 100 sein." >&2
    exit 1
  fi
done

for command in awk curl df docker flock grep sed ss stat systemctl tee ufw; do
  command -v "$command" >/dev/null || {
    echo "FEHLER: Erforderlicher Befehl fehlt: $command" >&2
    exit 1
  }
done

umask 077
install -d -m 700 "$STATUS_DIR"

exec 9>/run/lock/kahle-vinci-healthcheck.lock
if ! flock -n 9; then
  echo "KAHLE-Vinci-Healthcheck laeuft bereits."
  exit 0
fi

if systemctl is-active --quiet kahle-vinci-backup.service; then
  printf '%s backup-in-progress\n' "$(date --iso-8601=seconds)" >"$STATUS_DIR/last-skipped"
  echo "KAHLE-Vinci-Backup laeuft; Healthcheck wird uebersprungen."
  exit 0
fi

for unit in docker.service ssh.service fail2ban.service unattended-upgrades.service; do
  systemctl is-active --quiet "$unit" || fail "systemd unit not active: $unit"
done

ufw status | grep -q '^Status: active$' || fail "ufw is not active"
systemctl is-active --quiet kahle-vinci-backup.timer || fail "backup timer is not active"

containers=(
  caddy
  open-webui
  qdrant
  document-worker
  owui-file-proxy
  n8n
  kb-sync
  searxng
)

for container in "${containers[@]}"; do
  if ! docker inspect "$container" >/dev/null 2>&1; then
    fail "container missing: $container"
    continue
  fi

  state="$(docker inspect "$container" --format '{{.State.Status}}')"
  [[ "$state" == "running" ]] || fail "container not running: $container ($state)"

  health="$(docker inspect "$container" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')"
  [[ "$health" == "none" || "$health" == "healthy" ]] || fail "container unhealthy: $container ($health)"
done

endpoints=(
  "public-edge|$PUBLIC_EDGE_HEALTH_URL"
  'open-webui|http://127.0.0.1:3001/health'
  'n8n|http://127.0.0.1:5678/healthz'
  'qdrant|http://127.0.0.1:6333/healthz'
  'file-proxy|http://127.0.0.1:8091/health'
)

for endpoint in "${endpoints[@]}"; do
  name="${endpoint%%|*}"
  url="${endpoint#*|}"
  curl --fail --silent --show-error --max-time 10 "$url" >/dev/null 2>&1 \
    || fail "HTTP healthcheck failed: $name ($url)"
done

for port in 80 443; do
  listeners="$(ss -lntH "sport = :$port")"
  local_addresses="$(awk '{print $4}' <<<"$listeners")"

  grep -Eq "^0\.0\.0\.0:${port}$" <<<"$local_addresses" \
    || fail "expected public IPv4 listener missing: $port"

  if grep -Eq "^\[::\]:${port}$" <<<"$local_addresses"; then
    fail "unexpected public IPv6 listener: $port"
  fi
done
for port in 3001 5678 6333 8091; do
  listeners="$(ss -lntH "sport = :$port")"
  local_addresses="$(awk '{print $4}' <<<"$listeners")"

  if grep -Eq '^(0\.0\.0\.0|\[::\]):' <<<"$local_addresses"; then
    fail "localhost-only port is publicly bound: $port"
  fi
  grep -Eq "^127\.0\.0\.1:${port}$" <<<"$local_addresses" \
    || fail "expected localhost listener missing: $port"
done

disk_percent="$(df -P / | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"
inode_percent="$(df -Pi / | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"
(( disk_percent < MAX_DISK_PERCENT )) || fail "disk usage too high: ${disk_percent}%"
(( inode_percent < MAX_INODE_PERCENT )) || fail "inode usage too high: ${inode_percent}%"

last_success="$BACKUP_STATUS_DIR/last-success"
last_failure="$BACKUP_STATUS_DIR/last-failure"

if [[ ! -s "$last_success" ]]; then
  fail "backup success marker missing"
else
  now="$(date +%s)"
  backup_time="$(stat -c %Y "$last_success")"
  backup_age_hours="$(( (now - backup_time) / 3600 ))"
  (( backup_age_hours <= MAX_BACKUP_AGE_HOURS )) \
    || fail "last successful backup is too old: ${backup_age_hours}h"

  backup_file="$(sed -n 's/.* file=\([^ ]*\) sha256=.*/\1/p' "$last_success")"
  [[ -n "$backup_file" && -s "$backup_file" && -s "$backup_file.sha256" ]] \
    || fail "latest encrypted backup or checksum is missing"
fi

if [[ -s "$last_failure" && ( ! -e "$last_success" || "$last_failure" -nt "$last_success" ) ]]; then
  fail "latest backup attempt failed: $(cat "$last_failure")"
fi

timestamp="$(date --iso-8601=seconds)"

if (( ${#failures[@]} > 0 )); then
  {
    printf '%s status=FAILED\n' "$timestamp"
    printf -- '- %s\n' "${failures[@]}"
  } | tee "$STATUS_DIR/last-failure" >&2
  exit 1
fi

printf '%s status=OK disk=%s%% inodes=%s%%\n' \
  "$timestamp" "$disk_percent" "$inode_percent" \
  | tee "$STATUS_DIR/last-success"
rm -f -- "$STATUS_DIR/last-failure" "$STATUS_DIR/last-skipped"

