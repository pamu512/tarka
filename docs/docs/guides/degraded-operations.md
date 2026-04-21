# Degraded Operations Runbook

This runbook defines how Saarthi and Investigation surfaces behave when upstreams or LLM configuration are degraded.

## Copilot degraded modes

`POST /v1/chat` now includes:

- `copilot_mode`: `full` | `tools_only_deterministic` | `read_only_summary` | `offline`
- `degraded_reasons[]`: machine-readable causes (for example `openai_api_key_missing`, `tool_surface_empty`, `tool_errors_present`)

Expected operator behavior:

- `full`: normal analyst experience.
- `tools_only_deterministic`: LLM unavailable; assistant should still produce tool-backed artifacts.
- `read_only_summary`: LLM available but tool surface intentionally constrained (plain mode / no upstream tools).
- `offline`: reserved for hard failure paths where deterministic fallback cannot run.

## UI behavior expectations

- `frontend/src/pages/Investigation.tsx` renders a visible degraded banner when `copilot_mode != full` or `degraded_reasons[]` is present.
- Case-scoped Investigation now includes a context drawer that fetches:
  - `GET /v1/cases/{id}/graph`
  - `GET /v1/cases/{id}/decision-explanation`
- Decision explanation drawer shows `source` so analysts can distinguish:
  - `decision_audit` (healthy)
  - `decision_api_unreachable`, `decision_api_url_unset`, or `decision_api_http_*` (degraded)

## Bridge health fields to monitor

`services/collaboration-chat-bridge` exposes `GET /v1/health` fields that should be tracked in degraded incidents:

- `investigation_agent_configured`
- `slack_signing_configured`
- `slack_bot_configured`
- `teams_bridge_secret_configured`
- `plugin_bridge_secret_configured`
- `lark_verification_configured`
- `lark_reply_configured`
- `bridge_rate_limit_per_minute`
- `bridge_web_fetch_enabled`
- `bridge_attachment_max_bytes`

## End-to-end smoke check

Use the smoke script to verify the explanation chain after deploy:

```bash
python scripts/ci/investigation_e2e_smoke.py \
  --tenant-id demo \
  --decision-api-url http://localhost:8000 \
  --case-api-url http://localhost:8002
```

The script asserts this path:

1. `POST /v1/decisions/evaluate`
2. `POST /v1/cases`
3. `GET /v1/cases/{id}/decision-explanation`
4. `graph_decision_explanation.schema_id == "tarka.graph_decision_explanation/v1"`
