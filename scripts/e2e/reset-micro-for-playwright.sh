#!/usr/bin/env bash
# Reset durable Micro state and boot core-api for Playwright E2E (SQLite + DuckDB under a dedicated dir).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_MICRO="${ROOT}/deploy/docker-compose.micro.yml"
COMPOSE_E2E="${ROOT}/deploy/docker-compose.micro.e2e.yml"
export TARKA_MICRO_DATA_DIR="${TARKA_MICRO_DATA_DIR:-${ROOT}/.tarka-micro-e2e/data}"
export TARKA_MICRO_PORT="${TARKA_MICRO_PORT:-8000}"
export E2E_API_KEY="${E2E_API_KEY:-playwright-e2e-micro-key}"

if ! docker info >/dev/null 2>&1; then
  echo "error: Docker is not running or not reachable." >&2
  exit 1
fi

echo "Removing durable Micro data at ${TARKA_MICRO_DATA_DIR}..."
rm -rf "${TARKA_MICRO_DATA_DIR}"
mkdir -p "${TARKA_MICRO_DATA_DIR}/decision_logs" "${TARKA_MICRO_DATA_DIR}/lists" "${TARKA_MICRO_DATA_DIR}/ml_exports"
TARKA_MICRO_DATA_DIR="$(cd "${TARKA_MICRO_DATA_DIR}" && pwd)"
export TARKA_MICRO_DATA_DIR

echo "Building core-api..."
docker compose --project-directory "${ROOT}" -f "${COMPOSE_MICRO}" -f "${COMPOSE_E2E}" build core-api

echo "Running Alembic migrations..."
docker compose --project-directory "${ROOT}" -f "${COMPOSE_MICRO}" -f "${COMPOSE_E2E}" run --rm -T --no-deps core-api \
  sh -c 'alembic -c /app/config/decision_alembic.ini upgrade head && alembic -c /app/config/case_alembic.ini upgrade head'

echo "Starting Tarka Micro (E2E overlay)..."
docker compose --project-directory "${ROOT}" -f "${COMPOSE_MICRO}" -f "${COMPOSE_E2E}" up -d --no-build

BASE_URL="http://127.0.0.1:${TARKA_MICRO_PORT}"
echo "Waiting for API health (${BASE_URL}/v1/health)..."
deadline=$((SECONDS + 120))
code=""
while (( SECONDS < deadline )); do
  code="$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/v1/health" || true)"
  if [[ "${code}" == "200" ]]; then
    echo "Micro stack ready for E2E."
    exit 0
  fi
  sleep 0.5
done

echo "error: API did not become healthy within 120s (last HTTP status: ${code:-none})." >&2
docker compose --project-directory "${ROOT}" -f "${COMPOSE_MICRO}" -f "${COMPOSE_E2E}" ps >&2 || true
docker compose --project-directory "${ROOT}" -f "${COMPOSE_MICRO}" -f "${COMPOSE_E2E}" logs --tail 80 core-api >&2 || true
exit 1
