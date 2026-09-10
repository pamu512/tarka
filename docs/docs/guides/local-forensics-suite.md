# Desk Advise (investigation-agent)

The desktop forensics console (`tools/shadow` submodule, Tauri sidecar on `:8742`) is **removed**. Desk **Advise** is **investigation-agent** only.

## Day-1

Empty `OPENAI_BASE_URL` = Advise plane off (hide chrome). Setup asks for a BYO OpenAI-compat URL + key (optional model) or skip. OpenAI-compat covers OpenAI / Gemini compat / Bedrock gateway / Azure / vLLM. Keys stay in `infra/deploy/.env` — never in the browser (`VITE_*`).

```bash
# After setup wrote OPENAI_*:
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.investigation.yml \
  --env-file infra/deploy/.env \
  up -d --build
```

Helm: leave `investigationAgent.enabled` false unless the operator supplies that BYO endpoint. Prefer PlaneOff over half-on chrome.

Ingest analyze / scout stays on `shadow_agent` (`SHADOW_LLM_*` / `SHADOW_AGENT_URL`). See [SHADOW.md](../../../services/SHADOW.md).

## Advise context (planned)

Confluence / Wiki **read-only** sync into tenant OKF / RAG is the future path. Other knowledge connectors on request. SOP zip upload remains the air-gap bootstrap. Built-in playbooks are generic defaults only when the desk provides none.

See [Investigation Agent](../services/investigation-agent.md).
