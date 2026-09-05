#!/usr/bin/env bash
# One-command thin desk: lite + fraud-desk, then an honest evaluate receipt walk.
# Public path: `make doctor && make demo`. Deeper smoke: scripts/oss/first_decision_smoke.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
DEPLOY="$ROOT/infra/deploy"
if [[ ! -f "$DEPLOY/.env" ]]; then
  cp "$DEPLOY/env/community.env.example" "$DEPLOY/.env"
  echo 'ALLOW_INSECURE_NO_AUTH=true' >> "$DEPLOY/.env"
fi
if curl -sf http://127.0.0.1:8000/decisions/v1/health >/dev/null; then
  echo "[ok] evaluate already healthy — skipping compose; running receipt walk."
  exec python3 "$ROOT/scripts/oss/walk_receipts.py"
fi
python3 "$ROOT/scripts/oss/doctor.py" || {
  echo "[fail] doctor — fix the lines above, then: make doctor && make demo" >&2
  echo "CI-safe walk (no compose): PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_walk_receipts.py" >&2
  exit 1
}
python3 "$ROOT/scripts/oss/setup_llm_env.py" --env-file "$DEPLOY/.env" || true
docker compose \
  -f "$DEPLOY/docker-compose.lite.yml" \
  -f "$DEPLOY/docker-compose.fraud-desk.yml" \
  --env-file "$DEPLOY/.env" up -d --build
healthy=0
for _ in $(seq 1 90); do
  if curl -sf http://127.0.0.1:8000/decisions/v1/health >/dev/null; then
    healthy=1
    break
  fi
  sleep 2
done
if [[ "$healthy" -ne 1 ]]; then
  echo "[fail] health timeout — GET http://127.0.0.1:8000/decisions/v1/health never succeeded (3 min)." >&2
  echo "Hint: make doctor (ports 8000/8001/3000/5432/6379). Then: docker compose -f infra/deploy/docker-compose.lite.yml ps" >&2
  exit 1
fi
exec python3 "$ROOT/scripts/oss/walk_receipts.py"
