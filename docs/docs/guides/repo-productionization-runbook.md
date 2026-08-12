# Repo productionization runbook (AI + ops path)

**Date:** 2026-08-12  
**Scope:** Deploy readiness for trend loop, Shadow escalate-only defaults, Ops UI discovery, mock fail-closed in prod builds.

## Stack knobs

| Env | Where | Purpose |
|-----|--------|---------|
| `TREND_AGENT_DATA_DIR` | decision-api / core-api | SQLite for watchlist/baselines/drafts |
| `TREND_TICK_SKIP_LLM` | decision-api | Default `1` — tick uses policy escalate |
| `TREND_BASELINE_MIN_N` | decision-api | Min EWMA samples before evaluate (default `3`) |
| `TREND_WATCH_ON_INGEST` | orchestrator | `1` when `DECISION_API_URL` set |
| `SHADOW_ACTION_MODULATION` | orchestrator | Default `escalate_only` |
| `VITE_USE_API_MOCKS` | frontend | Forbidden as `true` in production builds |

## Always-on tick (no custom daemon)

```bash
# Host loop
DECISION_API_URL=http://127.0.0.1:8000 ./scripts/trend_tick_loop.sh

# Compose profile (v2 ingest stack)
docker compose -f infra/deploy/docker-compose.v2-ingest.yml --profile trend-tick up -d
```

Ops UI: **Ops calibration & trend** (`/ops/calibration`) → Run tick / drafts / HIL.  
API honesty: `GET /v1/ops/trend/posture`.

## Gateway

Production nginx already proxies `/api/decisions/` → `core-api` and `/api/investigation/` → investigation-agent ([frontend/nginx.conf](../../frontend/nginx.conf)). Trend ops and AgentRun use those prefixes — no extra location blocks required.

## Honesty invariants

- Trend drafts: `wasm_ready=false`, promote → `409 never_auto_promote`
- Shadow timeout: inconclusive `risk_score=50`, never clear-looking `0`
- Case brief: deterministic; `llm_used=true` rejected by case-api hook
- Frontend mocks: disabled in production builds; desk-strict blocks auto mocks on cases/calibration/QA/trend (SR-13 Done Degrade)
- SAR pre-filing: well-formed `fincen_xml` + `EFilingBatch` root (SR-10 depth floor; not full FinCEN XSD)

## Related specs

- [2026-08-12-ai-productionization-design.md](../superpowers/specs/2026-08-12-ai-productionization-design.md)
- [2026-08-11-omniscient-agent-run-design.md](../superpowers/specs/2026-08-11-omniscient-agent-run-design.md)
