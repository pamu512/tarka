#!/usr/bin/env bash
# Phase 9 — wait for the orchestrator aggregate health endpoint (confirms rule + shadow probes).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_URL="${TARKA_ORCHESTRATOR_BASE:-http://127.0.0.1:8790}"
deadline=$((SECONDS + 120))
echo "Probing ${BASE_URL}/health/full ..."
while (( SECONDS < deadline )); do
  if curl -fsS "${BASE_URL}/health/full" >/dev/null 2>&1; then
    echo "OK — orchestrator health/full returned HTTP 200."
    curl -fsS "${BASE_URL}/health/full" | head -c 2000
    echo ""
    exit 0
  fi
  sleep 1
done
echo "error: ${BASE_URL}/health/full did not succeed within 120s." >&2
cd "${ROOT}" && docker compose -f deploy/docker-compose.v2-ingest.yml ps >&2 || true
exit 1
