#!/bin/sh
set -eu

# Usage:
#   sh /home/node/.n8n/scripts/cleanup_file_artifacts.sh [days] [mode]
# Examples:
#   sh /home/node/.n8n/scripts/cleanup_file_artifacts.sh 15 dry-run
#   sh /home/node/.n8n/scripts/cleanup_file_artifacts.sh 15 delete

DAYS="${1:-15}"
MODE="${2:-dry-run}" # dry-run | delete

OWUI_ROOT="/mnt/open-webui-data"
WORKER_ROOT="/mnt/document-worker-data"

UPLOADS_DIR="${OWUI_ROOT}/uploads"
EDITED_DIR="${OWUI_ROOT}/edited"

echo "cleanup_start days=${DAYS} mode=${MODE}"

list_candidates() {
  target="$1"
  if [ -d "${target}" ]; then
    find "${target}" -type f -mtime +"${DAYS}" -print
  fi
}

delete_candidates() {
  target="$1"
  if [ -d "${target}" ]; then
    find "${target}" -type f -mtime +"${DAYS}" -print -delete
    # Remove empty subfolders afterwards (keep root folder itself).
    find "${target}" -mindepth 1 -type d -empty -delete
  fi
}

echo "target_uploads=${UPLOADS_DIR}"
echo "target_edited=${EDITED_DIR}"
echo "target_worker=${WORKER_ROOT}"

if [ "${MODE}" = "dry-run" ]; then
  list_candidates "${UPLOADS_DIR}"
  list_candidates "${EDITED_DIR}"
  list_candidates "${WORKER_ROOT}"
  echo "cleanup_done mode=dry-run"
  exit 0
fi

if [ "${MODE}" != "delete" ]; then
  echo "invalid_mode=${MODE} (allowed: dry-run|delete)" >&2
  exit 2
fi

delete_candidates "${UPLOADS_DIR}"
delete_candidates "${EDITED_DIR}"
delete_candidates "${WORKER_ROOT}"
echo "cleanup_done mode=delete"
