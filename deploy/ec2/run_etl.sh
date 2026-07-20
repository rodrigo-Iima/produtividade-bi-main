#!/usr/bin/env bash

set -u

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

mkdir -p .runtime
exec >> .runtime/etl.log 2>&1

echo "[$(date --iso-8601=seconds)] ETL cron started"

if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    . "$PROJECT_DIR/.env"
    set +a
fi

HEALTHCHECK_URL="${ETL_HEALTHCHECK_URL:-}"
RETRIES="${ETL_RETRIES:-1}"
RETRY_DELAY="${ETL_RETRY_DELAY:-30}"

ping_healthcheck() {
    local suffix="${1:-}"
    if [[ -z "$HEALTHCHECK_URL" ]]; then
        return 0
    fi

    if ! curl -fsS --max-time 10 --retry 3 -o /dev/null \
        "${HEALTHCHECK_URL%/}${suffix}"; then
        echo "[Alert] Healthcheck ping failed (${suffix:-success})"
    fi
}

ping_healthcheck "/start"

"$PROJECT_DIR/.venv/bin/python" -m operationalization run \
    --retries "$RETRIES" \
    --retry-delay "$RETRY_DELAY"
EXIT_CODE=$?

if [[ "$EXIT_CODE" -eq 0 ]]; then
    ping_healthcheck
    echo "[$(date --iso-8601=seconds)] ETL cron finished successfully"
else
    ping_healthcheck "/fail"
    echo "[$(date --iso-8601=seconds)] ETL cron failed with exit code $EXIT_CODE"
fi

exit "$EXIT_CODE"
