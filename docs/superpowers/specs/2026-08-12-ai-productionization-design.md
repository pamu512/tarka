# AI capability productionization

**Date:** 2026-08-12  
**Status:** Landed (OSS)  
**Related:** [omniscient AgentRun](./2026-08-11-omniscient-agent-run-design.md), [trend agent](./2026-08-12-trend-agent-design.md)

## Goal

Make force-multiplier AI claims true on a **product path**:

1. Always-on trend loop: watch → EWMA baselines → tick → triage/drafts  
2. Ops UI for drafts / HIL / reject / run tick  
3. AgentRun id visible on the case chat rail  

## Philosophy (unchanged)

- Decision-api / rules remain sole allow/deny authority.  
- Never invent velocity baselines.  
- Drafts stay `PENDING_VALIDATION` (`wasm_ready=false`); tick/auto promote stays `409 never_auto_promote`. Human + `backtest_job_id` + graph may set `gitops_ready` (not live Wasm) — [2026-08-13 agent-run spine](./2026-08-13-agent-run-spine-design.md).  
- Tick defaults to `skip_llm` (policy escalate).  

## Loop

```
ingest (high shadow risk | velocity indicators)
  → POST /v1/ops/trend/watch  (fire-and-forget; must not fail ingest)

cron | Ops “Run tick”
  → POST /v1/ops/trend/tick
      for each watched entity:
        agg_store.compute_features → observed counts
        update EWMA baselines in trend_store
        if min samples met → window_rows → run_trend_evaluation
        else → skip insufficient_baseline
```

### Window mapping

| Aggregate feature | metric_key | window |
|-------------------|------------|--------|
| `event_count_5m` | `sub_1min_velocity` | `sub_1min` |
| `event_count_24h` | `sub_24h_velocity` | `sub_24h` |
| `failed_auth_*` (if present) | `failed_auth_velocity` | matching window |

### Baselines

Per `(tenant_id, entity_id, metric_key)` EWMA mean/std. Minimum sample count (default 3) before evaluate. First observations only seed the baseline — never evaluate from a single point.

## Surfaces

- **API:** `/v1/ops/trend/watch`, `/tick`, plus existing evaluate/drafts/reject/hil/promote  
- **Ops UI:** OpsCalibration Trend panel  
- **Case chat:** display `agent_run_id`; fetch run for freshness / evidence_ids  

## Env

| Var | Default | Purpose |
|-----|---------|---------|
| `TREND_TICK_SKIP_LLM` | `1` | Tick uses policy path without LLM |
| `TREND_WATCH_ON_INGEST` | `1` (prod-like) | Orchestrator enqueues watch |
| `TREND_BASELINE_MIN_N` | `3` | Min EWMA samples before evaluate |
| `DECISION_API_URL` | — | Orchestrator watch target |

## Non-goals

- New long-lived trend worker daemon  
- Auto-promote Wasm  
- LIVE Ethoca / device / face calibration claims  
