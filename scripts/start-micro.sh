#!/usr/bin/env bash
# Boot Tarka Micro (single core-api container: decision + case APIs on SQLite + DuckDB).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT}/deploy/docker-compose.micro.yml"
export TARKA_MICRO_DATA_DIR="${TARKA_MICRO_DATA_DIR:-${ROOT}/.tarka-micro/data}"
export TARKA_MICRO_PORT="${TARKA_MICRO_PORT:-8000}"

mkdir -p "${TARKA_MICRO_DATA_DIR}/decision_logs" "${TARKA_MICRO_DATA_DIR}/lists" "${TARKA_MICRO_DATA_DIR}/ml_exports"
TARKA_MICRO_DATA_DIR="$(cd "${TARKA_MICRO_DATA_DIR}" && pwd)"
export TARKA_MICRO_DATA_DIR

if ! docker info >/dev/null 2>&1; then
  echo "error: Docker is not running or not reachable. Start Docker Desktop (or the daemon) and retry." >&2
  exit 1
fi

echo "Building core-api image..."
docker compose --project-directory "${ROOT}" -f "${COMPOSE_FILE}" build core-api

echo "Running Alembic migrations against SQLite (host dir: ${TARKA_MICRO_DATA_DIR})..."
docker compose --project-directory "${ROOT}" -f "${COMPOSE_FILE}" run --rm -T --no-deps core-api \
  sh -c 'alembic -c /app/config/decision_alembic.ini upgrade head && alembic -c /app/config/case_alembic.ini upgrade head'

echo "Starting Tarka Micro..."
docker compose --project-directory "${ROOT}" -f "${COMPOSE_FILE}" up -d --no-build

BASE_URL="http://127.0.0.1:${TARKA_MICRO_PORT}"
echo "Waiting for API health (${BASE_URL}/v1/health)..."
deadline=$((SECONDS + 120))
code=""
while (( SECONDS < deadline )); do
  code="$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/v1/health" || true)"
  if [[ "${code}" == "200" ]]; then
    echo ""
    echo "Ready."
    echo "  Core health:     ${BASE_URL}/v1/health"
    echo "  Decision API:    ${BASE_URL}/decisions/v1/health"
    echo "  Case API:        ${BASE_URL}/cases/v1/health"
    echo "  OpenAPI (dec):   ${BASE_URL}/decisions/openapi.json"
    echo "  OpenAPI (case):  ${BASE_URL}/cases/openapi.json"
    echo "  Durable files:   ${TARKA_MICRO_DATA_DIR}/tarka.sqlite"
    echo "                   ${TARKA_MICRO_DATA_DIR}/tarka-analytics.duckdb"
    exit 0
  fi
  sleep 0.5
done

echo "error: API did not become healthy within 120s (last HTTP status: ${code:-none})." >&2
docker compose --project-directory "${ROOT}" -f "${COMPOSE_FILE}" ps >&2 || true
docker compose --project-directory "${ROOT}" -f "${COMPOSE_FILE}" logs --tail 80 core-api >&2 || true
exit 1
