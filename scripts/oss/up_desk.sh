#!/usr/bin/env bash
# One-command thin desk: lite + fraud-desk, then an honest evaluate receipt walk.
# Public alias: `make demo`. Deeper smoke: scripts/oss/first_decision_smoke.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
DEPLOY="$ROOT/infra/deploy"
if [[ ! -f "$DEPLOY/.env" ]]; then
  cp "$DEPLOY/env/community.env.example" "$DEPLOY/.env"
  echo 'ALLOW_INSECURE_NO_AUTH=true' >> "$DEPLOY/.env"
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "[fail] docker not on PATH — install Docker Compose v2, then re-run make demo." >&2
  echo "CI-safe walk (no compose): PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_walk_receipts.py" >&2
  exit 1
fi
docker compose \
  -f "$DEPLOY/docker-compose.lite.yml" \
  -f "$DEPLOY/docker-compose.fraud-desk.yml" \
  --env-file "$DEPLOY/.env" up -d --build
for _ in $(seq 1 90); do
  if curl -sf http://127.0.0.1:8000/decisions/v1/health >/dev/null; then
    break
  fi
  sleep 2
done
exec python3 "$ROOT/scripts/oss/walk_receipts.py"
