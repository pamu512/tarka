#!/usr/bin/env bash
# Always-on trend tick without a custom daemon.
# Usage (repo root):
#   DECISION_API_URL=http://127.0.0.1:8000 ./scripts/trend_tick_loop.sh
# Compose profile:
#   docker compose -f infra/deploy/docker-compose.v2-ingest.yml --profile trend-tick up -d
set -euo pipefail

BASE="${DECISION_API_URL:-http://127.0.0.1:8000}"
INTERVAL="${TREND_TICK_INTERVAL_S:-60}"
LIMIT="${TREND_TICK_LIMIT:-50}"
API_KEY="${API_KEYS:-}"
API_KEY="${API_KEY%%,*}"

echo "trend_tick_loop base=${BASE} interval=${INTERVAL}s limit=${LIMIT}"

while true; do
  if [[ -n "${API_KEY}" ]]; then
    curl -sS -m 55 -X POST "${BASE%/}/v1/ops/trend/tick" \
      -H "Content-Type: application/json" \
      -H "x-api-key: ${API_KEY}" \
      -d "{\"limit\":${LIMIT},\"skip_llm\":true}" || true
  else
    curl -sS -m 55 -X POST "${BASE%/}/v1/ops/trend/tick" \
      -H "Content-Type: application/json" \
      -d "{\"limit\":${LIMIT},\"skip_llm\":true}" || true
  fi
  echo
  sleep "${INTERVAL}"
done
