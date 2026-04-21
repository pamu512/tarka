#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/docker-compose.yml"

echo "[investigation-smoke] starting compose stack (core + cases + graph + agent)"
docker compose -f "$COMPOSE_FILE" \
  --profile core \
  --profile cases \
  --profile graph \
  --profile agent \
  up -d --build

echo "[investigation-smoke] waiting briefly for service startup"
sleep 8

echo "[investigation-smoke] running decision->case->explanation assertion"
python "$ROOT_DIR/scripts/ci/investigation_e2e_smoke.py" "$@"

echo "[investigation-smoke] stopping compose stack"
docker compose -f "$COMPOSE_FILE" \
  --profile core \
  --profile cases \
  --profile graph \
  --profile agent \
  down
