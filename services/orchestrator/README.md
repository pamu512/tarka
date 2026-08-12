# tarka-orchestrator

Ingestion gateway (FastAPI). Container build: see `Dockerfile` (context ``).

## Shadow advisory policy (force-multiplier)

Shadow LLM output is **advisory**. Deterministic rules remain allow/deny authority.

| Env | Default | Meaning |
|-----|---------|---------|
| `SHADOW_ACTION_MODULATION` | `escalate_only` | May add `FLAG` / drop `ALLOW` on high Shadow risk; **never** clears `FLAG`→`ALLOW`. Set `legacy` only for explicit opt-in of the old downgrade path. `off` leaves actions unchanged. |
| `SHADOW_AUTORESOLVE_ENABLED` | unset/false | Inline `RESOLVED_AUTO` after ingest is **off**. Set `true` only if you intentionally re-enable machine auto-clear. |

Timeout / inconclusive Shadow payloads (`TIMEOUT_FALLBACK`, `confidence_metrics.timeout_fallback`) never modulate actions and never auto-resolve.

## Trend watch enqueue (force-multiplier)

On high Shadow risk or nonzero velocity indicators, ingest best-effort `POST {DECISION_API_URL}/v1/ops/trend/watch`. Failures are swallowed (ingest never fails).

| Env | Default | Meaning |
|-----|---------|---------|
| `TREND_WATCH_ON_INGEST` | on when `DECISION_API_URL` set; off if `0`/`false` | Enqueue entity onto trend watchlist |
| `DECISION_API_URL` | required for watch | decision-api base (e.g. `http://decision-api:8000`) |

Tick loop is **not** in the orchestrator — use `scripts/trend_tick_loop.sh` or compose profile `trend-tick`. See [repo-productionization-runbook.md](../../docs/docs/guides/repo-productionization-runbook.md).
