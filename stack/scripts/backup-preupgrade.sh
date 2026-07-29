#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="/opt/kahle-vinci"
COMPOSE_FILE="$PROJECT_ROOT/stack/docker-compose.yml"
ENV_FILE="$PROJECT_ROOT/stack/.env.smoke"
TIMESTAMP="${1:-$(date +%Y%m%d-%H%M%S)}"
BACKUP_DIR="/var/backups/kahle-vinci/$TIMESTAMP"
STACK_STOPPED=0

compose() {
  sudo docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

restart_if_needed() {
  exit_code=$?
  trap - EXIT
  if (( STACK_STOPPED == 1 )); then
    echo "=== Stack wieder starten ==="
    compose up -d || true
  fi
  if (( exit_code != 0 )); then
    echo "FEHLER: Backup in Zeile ${BASH_LINENO[0]:-unbekannt} abgebrochen (Exit $exit_code)." >&2
  fi
  exit "$exit_code"
}

trap restart_if_needed EXIT

for required in \
  "$PROJECT_ROOT" \
  "$ENV_FILE" \
  "$COMPOSE_FILE"
do
  if [[ ! -e "$required" ]]; then
    echo "FEHLER: Erforderlicher Pfad fehlt: $required" >&2
    exit 1
  fi
done

for volume_path in \
  /var/lib/docker/volumes/open-webui/_data \
  /var/lib/docker/volumes/stack_qdrant_data/_data \
  /var/lib/docker/volumes/stack_document_worker_data/_data
do
  if ! sudo test -d "$volume_path"; then
    echo "FEHLER: Docker-Volume-Pfad fehlt: $volume_path" >&2
    exit 1
  fi
done

sudo install -d -m 700 "$BACKUP_DIR"

echo "=== Stack stoppen ==="
compose down
STACK_STOPPED=1

echo "=== Open WebUI sichern ==="
sudo tar --numeric-owner --xattrs --acls \
  -czf "$BACKUP_DIR/open-webui-volume.tar.gz" \
  -C /var/lib/docker/volumes/open-webui/_data .

echo "=== Qdrant sichern ==="
sudo tar --numeric-owner --xattrs --acls \
  -czf "$BACKUP_DIR/qdrant-volume.tar.gz" \
  -C /var/lib/docker/volumes/stack_qdrant_data/_data .

echo "=== Document Worker sichern ==="
sudo tar --numeric-owner --xattrs --acls \
  -czf "$BACKUP_DIR/document-worker-volume.tar.gz" \
  -C /var/lib/docker/volumes/stack_document_worker_data/_data .

echo "=== Projekt und Host-Daten sichern ==="
sudo tar --numeric-owner --xattrs --acls \
  -czf "$BACKUP_DIR/kahle-vinci-project.tar.gz" \
  -C /opt kahle-vinci

archives=(
  "$BACKUP_DIR/open-webui-volume.tar.gz"
  "$BACKUP_DIR/qdrant-volume.tar.gz"
  "$BACKUP_DIR/document-worker-volume.tar.gz"
  "$BACKUP_DIR/kahle-vinci-project.tar.gz"
)

echo "=== Archive technisch prüfen ==="
for archive in "${archives[@]}"; do
  echo "Prüfe: $archive"
  sudo test -s "$archive"
  sudo gzip -t "$archive"
  sudo tar -tzf "$archive" >/dev/null
done

echo "=== Prüfsummen erzeugen ==="
sudo sh -c "cd '$BACKUP_DIR' && sha256sum *.tar.gz > SHA256SUMS.txt"
sudo find "$BACKUP_DIR" -maxdepth 1 -type f -exec chmod 600 {} +
sudo chmod 700 "$BACKUP_DIR"

echo "=== Stack wieder starten ==="
compose up -d
STACK_STOPPED=0

echo "=== Containerstatus ==="
compose ps

echo "=== Backup-Dateien ==="
sudo ls -lh "$BACKUP_DIR"

echo "=== SHA256 ==="
sudo cat "$BACKUP_DIR/SHA256SUMS.txt"

echo "BACKUP_DIR=$BACKUP_DIR"

trap - EXIT
