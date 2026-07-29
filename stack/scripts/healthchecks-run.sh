#!/usr/bin/env bash
set -uo pipefail

if (( $# < 2 )); then
  echo "Usage: $0 <URL_ENV_NAME> <command> [args...]" >&2
  exit 64
fi

URL_ENV_NAME="$1"
shift

if ! [[ "$URL_ENV_NAME" =~ ^HEALTHCHECK_[A-Z0-9_]+_URL$ ]]; then
  echo "FEHLER: Ungueltiger Healthchecks-Variablenname." >&2
  exit 64
fi

BASE_URL="${!URL_ENV_NAME:-}"
BASE_URL="${BASE_URL%/}"

if ! [[ "$BASE_URL" =~ ^https://hc-ping\.com/[A-Za-z0-9_-]+$ ]]; then
  echo "FEHLER: $URL_ENV_NAME fehlt oder hat ein ungueltiges Format." >&2
  exit 78
fi

for command in curl date hostname; do
  command -v "$command" >/dev/null || {
    echo "FEHLER: Erforderlicher Befehl fehlt: $command" >&2
    exit 69
  }
done

send_ping() {
  local suffix="$1"
  local result="$2"
  local exit_status="$3"
  local body

  body="host=$(hostname) check=$URL_ENV_NAME result=$result exit=$exit_status time=$(date --iso-8601=seconds)"

  curl \
    --fail \
    --silent \
    --show-error \
    --retry 2 \
    --retry-delay 2 \
    --retry-connrefused \
    --connect-timeout 5 \
    --max-time 15 \
    --request POST \
    --header 'Content-Type: text/plain; charset=utf-8' \
    --data-binary "$body" \
    "$BASE_URL$suffix" \
    >/dev/null
}

if ! send_ping "/start" "started" "-"; then
  echo "WARNUNG: Healthchecks.io-Startsignal konnte nicht gesendet werden." >&2
fi

"$@"
EXIT_STATUS=$?

if (( EXIT_STATUS == 0 )); then
  if ! send_ping "" "success" "$EXIT_STATUS"; then
    echo "WARNUNG: Healthchecks.io-Erfolgssignal konnte nicht gesendet werden." >&2
  fi
else
  if ! send_ping "/fail" "failure" "$EXIT_STATUS"; then
    echo "WARNUNG: Healthchecks.io-Fehlersignal konnte nicht gesendet werden." >&2
  fi
fi

exit "$EXIT_STATUS"

