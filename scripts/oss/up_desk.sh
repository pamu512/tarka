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
# Host ports (honor TARKA_*_PORT remaps from env or .env; defaults match compose).
env_val() { # $1=VAR $2=default
  local v="${!1:-}"
  if [[ -z "$v" && -f "$DEPLOY/.env" ]]; then
    v="$(grep -E "^$1=" "$DEPLOY/.env" | tail -1 | cut -d= -f2- || true)"
  fi
  echo "${v:-$2}"
}
CORE_PORT="$(env_val TARKA_CORE_PORT 8000)"
GRAPH_PORT="$(env_val TARKA_GRAPH_PORT 8001)"
FRONTEND_PORT="$(env_val TARKA_FRONTEND_PORT 3000)"
if curl -sf "http://127.0.0.1:${CORE_PORT}/decisions/v1/health" >/dev/null; then
  echo "[ok] evaluate already healthy — skipping compose; running receipt walk."
  exec python3 "$ROOT/scripts/oss/walk_receipts.py"
fi
python3 "$ROOT/scripts/oss/doctor.py" || {
  echo "[fail] doctor — fix the lines above, then: make doctor && make demo" >&2
  echo "CI-safe walk (no compose): PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_walk_receipts.py" >&2
  exit 1
}
python3 "$ROOT/scripts/oss/setup_llm_env.py" --env-file "$DEPLOY/.env" || true
compose_args=(
  docker compose
  -f "$DEPLOY/docker-compose.lite.yml"
  -f "$DEPLOY/docker-compose.fraud-desk.yml"
  --env-file "$DEPLOY/.env"
)
# Desk Advise = investigation-agent when OPENAI_BASE_URL is set. Empty = plane off.
if grep -qE '^OPENAI_BASE_URL=.+' "$DEPLOY/.env"; then
  compose_args+=(-f "$DEPLOY/docker-compose.investigation.yml")
fi
"${compose_args[@]}" up -d --build
healthy=0
for _ in $(seq 1 90); do
  if curl -sf "http://127.0.0.1:${CORE_PORT}/decisions/v1/health" >/dev/null; then
    healthy=1
    break
  fi
  sleep 2
done
if [[ "$healthy" -ne 1 ]]; then
  echo "[fail] health timeout — GET http://127.0.0.1:${CORE_PORT}/decisions/v1/health never succeeded (3 min)." >&2
  echo "Hint: make doctor (ports 8000/8001/3000/5432/6379). Then: docker compose -f infra/deploy/docker-compose.lite.yml ps" >&2
  exit 1
fi
# Report every default-stack plane, not just core-api (walkthrough S2: a dead
# graph-service or frontend used to pass the health gate silently).
probe() { # $1=name $2=url
  if curl -sf "$2" >/dev/null; then
    echo "[ok] $1 healthy — $2"
  else
    echo "[fail] $1 NOT healthy — $2 (docker compose -f infra/deploy/docker-compose.lite.yml ps; logs <svc>)"
  fi
}
probe "graph-service" "http://127.0.0.1:${GRAPH_PORT}/v1/health"
if curl -sf -o /dev/null "http://127.0.0.1:${FRONTEND_PORT}/" ; then
  echo "[ok] frontend healthy — http://127.0.0.1:${FRONTEND_PORT}/"
else
  echo "[fail] frontend NOT healthy — http://127.0.0.1:${FRONTEND_PORT}/ (docker compose -f infra/deploy/docker-compose.lite.yml ps frontend)"
fi
exec python3 "$ROOT/scripts/oss/walk_receipts.py"
