#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="${1:-$ROOT/deploy/local-ai/.env.local}"

set -a
source "$ENV_FILE"
set +a

if [[ "${AGENTICSEEK_DIR:-}" == *"\$USER"* ]]; then
  AGENTICSEEK_DIR="${AGENTICSEEK_DIR/\$USER/$USER}"
fi

COMPOSE_CMD=(
  docker compose
  --project-name local-ai-stack
  --env-file "$ENV_FILE"
  -f "$AGENTICSEEK_DIR/docker-compose.yml"
  -f "$ROOT/deploy/local-ai/docker-compose.addons.yml"
)

echo "Checking service endpoints..."
curl -fsS "${OLLAMA_BASE_URL%/}/api/tags" >/dev/null
curl -fsS "http://localhost:${AGENTIC_BACKEND_PORT:-7777}/health" >/dev/null
curl -fsS "http://localhost:${AGENTIC_FRONTEND_PORT:-3010}" >/dev/null
curl -fsS "http://localhost:${OPEN_WEBUI_PORT:-3001}" >/dev/null
curl -fsS "http://localhost:${N8N_PORT:-5678}/healthz" >/dev/null
curl -fsS "http://localhost:${SEARXNG_PORT:-8080}" >/dev/null

echo "Verifying n8n container can reach Ollama..."
"${COMPOSE_CMD[@]}" exec -T n8n node -e "fetch(process.env.OLLAMA_BASE_URL + '/api/tags').then((r)=>{if(!r.ok){throw new Error('HTTP '+r.status)};return r.text();}).then((t)=>{console.log(t.slice(0, 160));}).catch((e)=>{console.error(e);process.exit(1);});"

echo "All verification checks passed."
