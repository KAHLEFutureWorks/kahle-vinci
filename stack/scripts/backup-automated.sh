#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/kahle-vinci}"
COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_ROOT/stack/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/stack/.env.smoke}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/kahle-vinci}"
RECIPIENT_FILE="${RECIPIENT_FILE:-/etc/kahle-vinci/backup-recipient.txt}"
RETENTION_DAYS="${RETENTION_DAYS:-21}"
STATUS_DIR="${STATUS_DIR:-/var/lib/kahle-vinci-backup}"
BACKUP_READER_GROUP="${BACKUP_READER_GROUP:-kahle-backup-readers}"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
STAGING_DIR="$BACKUP_ROOT/.staging-$TIMESTAMP"
ENCRYPTED_DIR="$BACKUP_ROOT/encrypted"
OUTPUT_FILE="$ENCRYPTED_DIR/kahle-vinci-$TIMESTAMP.tar.age"
OUTPUT_HASH="$OUTPUT_FILE.sha256"
PARTIAL_FILE="$OUTPUT_FILE.partial"
STACK_STOPPED=0
BACKUP_COMPLETE=0

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

restart_stack() {
  if (( STACK_STOPPED == 1 )); then
    echo "=== Stack wieder starten ==="
    compose up -d --wait --wait-timeout 120
    STACK_STOPPED=0
  fi
}

cleanup() {
  exit_code=$?
  trap - EXIT

  if (( STACK_STOPPED == 1 )); then
    restart_stack || true
  fi

  if (( exit_code != 0 )); then
    rm -f -- "$PARTIAL_FILE"
    printf '%s exit=%s staging=%s\n' "$(date --iso-8601=seconds)" "$exit_code" "$STAGING_DIR" \
      >"$STATUS_DIR/last-failure"
    echo "FEHLER: Automatisches Backup abgebrochen (Exit $exit_code)." >&2
  elif (( BACKUP_COMPLETE == 1 )); then
    rm -rf -- "$STAGING_DIR"
  fi

  exit "$exit_code"
}

if (( EUID != 0 )); then
  echo "FEHLER: Dieses Skript muss als root laufen." >&2
  exit 1
fi

if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || (( RETENTION_DAYS < 1 )); then
  echo "FEHLER: RETENTION_DAYS muss eine positive ganze Zahl sein." >&2
  exit 1
fi

for command in age chgrp docker find flock getent gzip sha256sum tar; do
  command -v "$command" >/dev/null || {
    echo "FEHLER: Erforderlicher Befehl fehlt: $command" >&2
    exit 1
  }
done

if ! getent group "$BACKUP_READER_GROUP" >/dev/null; then
  echo "FEHLER: Backup-Lesegruppe fehlt: $BACKUP_READER_GROUP" >&2
  exit 1
fi

exec 9>/run/lock/kahle-vinci-backup.lock
if ! flock -n 9; then
  echo "FEHLER: Ein anderes KAHLE-Vinci-Backup laeuft bereits." >&2
  exit 1
fi

for required in "$PROJECT_ROOT" "$COMPOSE_FILE" "$ENV_FILE" "$RECIPIENT_FILE"; do
  [[ -e "$required" ]] || {
    echo "FEHLER: Erforderlicher Pfad fehlt: $required" >&2
    exit 1
  }
done

for volume_path in \
  /var/lib/docker/volumes/open-webui/_data \
  /var/lib/docker/volumes/stack_qdrant_data/_data \
  /var/lib/docker/volumes/stack_document_worker_data/_data
do
  [[ -d "$volume_path" ]] || {
    echo "FEHLER: Docker-Volume-Pfad fehlt: $volume_path" >&2
    exit 1
  }
done

RECIPIENT="$(tr -d '\r\n' <"$RECIPIENT_FILE")"
[[ "$RECIPIENT" == age1* ]] || {
  echo "FEHLER: Ungueltiger age-Empfaengerschluessel." >&2
  exit 1
}

umask 077
install -d -o root -g "$BACKUP_READER_GROUP" -m 710 "$BACKUP_ROOT"
install -d -o root -g root -m 700 "$STAGING_DIR" "$STATUS_DIR"
install -d -o root -g "$BACKUP_READER_GROUP" -m 750 "$ENCRYPTED_DIR"
trap cleanup EXIT

{
  echo "created=$(date --iso-8601=seconds)"
  echo "hostname=$(hostname)"
  echo "open_webui_image=$(docker inspect open-webui --format '{{.Config.Image}}' 2>/dev/null || true)"
  echo "middleware_sha256=$(sha256sum "$PROJECT_ROOT/stack/open-webui-overrides/open_webui/utils/middleware.py" | awk '{print $1}')"
} >"$STAGING_DIR/BACKUP-INFO.txt"

echo "=== Stack stoppen ==="
STACK_STOPPED=1
compose down

echo "=== Open WebUI sichern ==="
tar --numeric-owner --xattrs --acls \
  -czf "$STAGING_DIR/open-webui-volume.tar.gz" \
  -C /var/lib/docker/volumes/open-webui/_data .

echo "=== Qdrant sichern ==="
tar --numeric-owner --xattrs --acls \
  -czf "$STAGING_DIR/qdrant-volume.tar.gz" \
  -C /var/lib/docker/volumes/stack_qdrant_data/_data .

echo "=== Document Worker sichern ==="
tar --numeric-owner --xattrs --acls \
  -czf "$STAGING_DIR/document-worker-volume.tar.gz" \
  -C /var/lib/docker/volumes/stack_document_worker_data/_data .

echo "=== Projekt und Host-Daten sichern ==="
tar --numeric-owner --xattrs --acls \
  -czf "$STAGING_DIR/kahle-vinci-project.tar.gz" \
  -C /opt kahle-vinci

archives=(
  "$STAGING_DIR/open-webui-volume.tar.gz"
  "$STAGING_DIR/qdrant-volume.tar.gz"
  "$STAGING_DIR/document-worker-volume.tar.gz"
  "$STAGING_DIR/kahle-vinci-project.tar.gz"
)

echo "=== Archive technisch pruefen ==="
for archive in "${archives[@]}"; do
  [[ -s "$archive" ]]
  gzip -t "$archive"
  tar -tzf "$archive" >/dev/null
done

(
  cd "$STAGING_DIR"
  sha256sum ./*.tar.gz >SHA256SUMS.txt
  sha256sum -c SHA256SUMS.txt
)

echo "=== Stack wieder starten ==="
restart_stack

echo "=== Backup verschluesseln ==="
tar -C "$BACKUP_ROOT" -cf - ".staging-$TIMESTAMP" \
  | age --recipient "$RECIPIENT" --output "$PARTIAL_FILE"

[[ -s "$PARTIAL_FILE" ]]
mv -- "$PARTIAL_FILE" "$OUTPUT_FILE"
(
  cd "$ENCRYPTED_DIR"
  sha256sum "$(basename "$OUTPUT_FILE")" >"$(basename "$OUTPUT_HASH")"
)
chgrp "$BACKUP_READER_GROUP" "$OUTPUT_FILE" "$OUTPUT_HASH"
chmod 640 "$OUTPUT_FILE" "$OUTPUT_HASH"

echo "=== Rotation: $RETENTION_DAYS Tage ==="
find "$ENCRYPTED_DIR" -maxdepth 1 -type f \
  \( -name 'kahle-vinci-*.tar.age' -o -name 'kahle-vinci-*.tar.age.sha256' \) \
  -mtime "+$RETENTION_DAYS" -delete

printf '%s file=%s sha256=%s\n' \
  "$(date --iso-8601=seconds)" \
  "$OUTPUT_FILE" \
  "$(awk '{print $1}' "$OUTPUT_HASH")" \
  >"$STATUS_DIR/last-success"
rm -f -- "$STATUS_DIR/last-failure"

BACKUP_COMPLETE=1

echo "BACKUP_FILE=$OUTPUT_FILE"
echo "BACKUP_HASH=$OUTPUT_HASH"

