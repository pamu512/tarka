# Omniscient AI — AgentRun spine + Shadow demotion

**Date:** 2026-08-11  
**Status:** Implemented (OSS)  
**Related:** [repository convergence §5](2026-07-25-repository-convergence-design.md), investigation-agent, orchestrator Shadow ingest

## Philosophy

**Omniscient** means a shared, freshness-aware **read model** for case/entity/trace evidence — not autonomous allow/deny or case closure.

- Decision-api / rules remain sole allow/deny authority.
- Shadow and Saarthi (investigation-agent) are **analyst force-multipliers**.
- AI may escalate suspicion and draft narratives; it must **never** clear a deterministic `FLAG` or auto-resolve a case by default.

## Track B — Shadow demotion

| Knob | Default | Effect |
|------|---------|--------|
| `SHADOW_ACTION_MODULATION` | `escalate_only` | High risk may add `FLAG` / drop `ALLOW`; never `FLAG`→`ALLOW` |
| `SHADOW_AUTORESOLVE_ENABLED` | unset/false | Inline `RESOLVED_AUTO` after ingest is off |
| Timeout fallback | inconclusive | `risk_score=50`, `confidence_metrics.timeout_fallback=true` |

See `services/orchestrator/README.md` and `services/shadow_agent/README.md`.

## Track A — AgentRun + context assembler

### Context snapshot

`investigation_agent.context_assembler.assemble_context_snapshot` emits:

- `schema_id`: `tarka.context_snapshot/v1`
- Per-source `freshness` (`present` | `missing`) — never invents fields
- `artifacts[]` with `evidence_id`, `content_hash`, excerpt

### AgentRun

SQLite under `INVESTIGATION_DATA_DIR` (`COPILOT_AGENT_RUN_DB_NAME`):

- Persisted on each chat turn; response includes `agent_run_id`
- `GET /v1/agent-runs/{run_id}?tenant_id=`
- `GET /v1/agent-runs?turn_id=&tenant_id=`

### Case brief hook

`POST /v1/internal/case-brief` — deterministic markdown from the assembler (no LLM). Satisfies case-api `fire_case_brief`. Auth: `INVESTIGATION_INTERNAL_SECRET` / `x-internal-secret`.

**case-api persistence:** `fire_case_brief` writes the returned `brief_markdown` as a system `CaseComment` (not discarded). On failure it records an unreachable-endpoint fallback — not an LLM outage message.

## Out of scope

- Shadow desktop mutating tools
- LIVE calibration claims
- Auto-promoting Wasm rules from the trend agent (drafts stay `PENDING_VALIDATION`)

## Track C — Trend agent (landed)

Forensic statistician loop in `services/analytics` (`trend_agent.py`): seasonal/HIL systemic resolve, unmanaged Z>4 → triage + `PENDING_VALIDATION` drafts, LLM timeout fail-closed. Spec: [2026-08-12-trend-agent-design.md](2026-08-12-trend-agent-design.md).

**Production path:** watch → EWMA baselines → tick → Ops UI. Spec: [2026-08-12-ai-productionization-design.md](2026-08-12-ai-productionization-design.md).
