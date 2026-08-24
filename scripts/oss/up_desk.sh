#!/usr/bin/env bash
# One-command OSS thin desk: evaluate-only lite + fraud-desk UI, then first-decision smoke.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
DEPLOY="$ROOT/infra/deploy"
if [[ ! -f "$DEPLOY/.env" ]]; then
  cp "$DEPLOY/env/community.env.example" "$DEPLOY/.env"
  echo 'ALLOW_INSECURE_NO_AUTH=true' >> "$DEPLOY/.env"
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
exec python3 "$ROOT/scripts/oss/first_decision_smoke.py"
