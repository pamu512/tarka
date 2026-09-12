#!/usr/bin/env bash
# Product skin: lite + fraud-desk + product overlay + receipt walk.
# Public path: `make doctor && make product`. Demo stays `make demo`.
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
  echo "[fail] doctor — fix the lines above, then: make doctor && make product" >&2
  echo "CI-safe walk (no compose): PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_walk_receipts.py" >&2
  exit 1
}
python3 "$ROOT/scripts/oss/setup_llm_env.py" --env-file "$DEPLOY/.env" || true
# Bake Hunt chrome from the provision file when TARKA_HUNT_ENABLED is unset.
if [[ -z "${TARKA_HUNT_ENABLED:-}" ]]; then
  TARKA_HUNT_ENABLED="$(
    python3 -c "
import json
from pathlib import Path
p = Path(r'$DEPLOY/desk_provision.example.json')
data = json.loads(p.read_text()) if p.is_file() else {}
hunt = data.get('hunt') if isinstance(data, dict) else None
on = True if not isinstance(hunt, dict) or 'enabled' not in hunt else bool(hunt.get('enabled'))
print('1' if on else '0')
"
  )"
  export TARKA_HUNT_ENABLED
fi
compose_args=(
  docker compose
  -f "$DEPLOY/docker-compose.lite.yml"
  -f "$DEPLOY/docker-compose.fraud-desk.yml"
  -f "$DEPLOY/docker-compose.product.yml"
  --env-file "$DEPLOY/.env"
)
# Desk Advise = investigation-agent when OPENAI_BASE_URL is set. Empty = plane off.
if grep -qE '^OPENAI_BASE_URL=.+' "$DEPLOY/.env"; then
  compose_args+=(-f "$DEPLOY/docker-compose.investigation.yml")
fi
# Ingest sidecar = shadow_agent when SHADOW_LLM_BASE_URL is set (not desk Advise).
if grep -qE '^SHADOW_LLM_BASE_URL=.+' "$DEPLOY/.env"; then
  compose_args+=(--profile llm)
fi
"${compose_args[@]}" up -d --build
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
