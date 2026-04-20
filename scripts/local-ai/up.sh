#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="${1:-$ROOT/deploy/local-ai/.env.local}"

"$ROOT/scripts/local-ai/bootstrap-agenticseek.sh" "$ENV_FILE"

set -a
source "$ENV_FILE"
set +a

if [[ "${AGENTICSEEK_DIR:-}" == *"\$USER"* ]]; then
  AGENTICSEEK_DIR="${AGENTICSEEK_DIR/\$USER/$USER}"
fi

if ! curl -fsS "${OLLAMA_BASE_URL%/}/api/tags" >/dev/null 2>&1; then
  echo "Starting Ollama at ${OLLAMA_HOST:-0.0.0.0:11434}..."
  OLLAMA_HOST="${OLLAMA_HOST:-0.0.0.0:11434}" nohup ollama serve >/tmp/ollama-local-ai.log 2>&1 &
  sleep 3
fi

curl -fsS "${OLLAMA_BASE_URL%/}/api/tags" >/dev/null
ollama pull "${OLLAMA_MODEL}"

docker compose \
  --project-name local-ai-stack \
  --env-file "$ENV_FILE" \
  -f "$AGENTICSEEK_DIR/docker-compose.yml" \
  -f "$ROOT/deploy/local-ai/docker-compose.addons.yml" \
  --profile full \
  --profile addons \
  up -d --build

echo "Stack started."
echo "AgenticSeek UI: http://localhost:${AGENTIC_FRONTEND_PORT:-3010}"
echo "AgenticSeek API: http://localhost:${AGENTIC_BACKEND_PORT:-7777}/health"
echo "Open WebUI: http://localhost:${OPEN_WEBUI_PORT:-3001}"
echo "n8n: http://localhost:${N8N_PORT:-5678}"
echo "SearXNG: http://localhost:${SEARXNG_PORT:-8080}"
