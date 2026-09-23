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

## Advise context (air-gap SOP zip)

SOP zip is the air-gap bootstrap. Confluence / Wiki **read-only** sync into tenant OKF / RAG is later. Other connectors on request. This repo does not ship a Confluence connector. Built-in playbooks are generic defaults only when the desk provides none.

```bash
# After setup wrote OPENAI_* (empty URL = Advise plane off):
python3 scripts/oss/advise_sop_import.py --zip /path/to/tenant-okf.zip --tenant-id YOUR_TENANT
# Optional: export the absolute OKF_TENANT_OVERLAYS_PATH printed on stderr.
# Omit it to use compose default ../../knowledge/tenants (from infra/deploy/).
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.investigation.yml \
  --env-file infra/deploy/.env \
  up -d --build
```

`validate_okf_bundle --scope tenant` must exit 0 before the overlay is staged.
The agent mount is read-only. Retrieval smoke requires cites or an honest
abstain — zero cites is not success. Tenant SOP payloads stay out of git.

See [Investigation Agent](../services/investigation-agent.md).
