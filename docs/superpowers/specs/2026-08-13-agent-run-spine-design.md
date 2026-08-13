# AgentRun spine — graph, lifecycle HIL, human trend promote

**Date:** 2026-08-13  
**Status:** Approved (spec)  
**Related:** [omniscient AgentRun](./2026-08-11-omniscient-agent-run-design.md), [trend agent](./2026-08-12-trend-agent-design.md), [AI productionization](./2026-08-12-ai-productionization-design.md)

Amends productionization: `POST /v1/ops/trend/drafts/{id}/promote` stays `409 never_auto_promote` for tick/auto and for any call missing actor or `backtest_job_id`. A **human** call with both may return 200 meaning **GitOps-ready**, not live Wasm.

## Goal

One AgentRun read model for Shadow, investigation chat, and trend tick, then two HIL writers on that spine:

1. Graph-aware runs (cite `evidence_ids`; banner when graph is missing)
2. Case lifecycle proposals (analyst confirms via existing `PUT /v1/cases/{id}/status`)
3. Human trend promote → GitOps-ready draft (`PENDING_VALIDATION`, `wasm_ready=false`)

## Philosophy (unchanged)

- Decision-api / rules remain sole allow/deny authority.
- AI never auto-resolves a case and never auto-promotes Wasm.
- Missing sources are `freshness=missing` — never invented.
- Ingest must not fail because investigation-agent is down.

## Architecture

investigation-agent **owns** AgentRun SQLite (`persist_agent_run`, `GET /v1/agent-runs/{id}`). No new service.

```
ingest → decision-api (allow/deny) → client
  │
  ├─ fire-and-forget Shadow analyze ─► POST /v1/internal/agent-runs
  └─ fire-and-forget trend tick     ─► POST /v1/internal/agent-runs

case chat ─► investigation-agent ─► AgentRun (sync persist)
                │
                ├─ propose_case_status (graph required) → pending proposal
                │     confirm = PUT /v1/cases/{id}/status (audit unchanged)
                └─ human trend promote (graph required, backtest_job_id + actor)
                      → GitOps-ready, still PENDING_VALIDATION
```

Callers of the internal POST: **orchestrator** (after Shadow returns) and **decision-api** (after tick). Same fire-and-forget pattern as `maybe_enqueue_trend_watch` (2s timeout, log warning, never raise).

## Graph policy

| Surface | Graph `freshness≠present` |
|---------|---------------------------|
| Chat / Shadow narrative | Allowed. Run tagged `graph_missing=true`. UI banner. Claims still carry `evidence_ids` (may be empty). |
| `propose_case_status` | `409 graph_required` |
| Human trend promote | `409 graph_required` |

`assemble_context_snapshot` already records `graph_neighborhood` as present or missing. Add a boolean `graph_missing` on the AgentRun response (true when that source is missing). Do not invent graph artifacts.

## Components

### Reuse

- `investigation_agent.agent_run_store.persist_agent_run` + `GET /v1/agent-runs/{id}`
- `assemble_context_snapshot` (`tarka.context_snapshot/v1`)
- `POST /v1/internal/case-brief` auth: `INVESTIGATION_INTERNAL_SECRET` / `x-internal-secret`
- `maybe_enqueue_trend_watch` fire-and-forget in `transaction_ingest.py`
- `PUT /v1/cases/{id}/status` (`case_transition_api.py`) — only the human confirm
- `backtest_before_promote_gate(require_job=True)`
- Case chat rail already displays `agent_run_id`

### Add

1. `POST /v1/internal/agent-runs` on investigation-agent (same auth as case-brief). Body maps 1:1 onto `persist_agent_run` plus `source` ∈ `chat` | `shadow` | `trend`.
2. Orchestrator + decision-api callers (timeout 2s, never fail parent request).
3. `graph_missing` on run GET/chat response.
4. Tool `propose_case_status` + SQLite `case_status_proposals` next to AgentRun (`pending` \| `confirmed` \| `rejected`). `GET /v1/case-status-proposals?case_id=&tenant_id=` for the SPA. Confirm in UI calls existing PUT, then marks `confirmed`. Proposal cannot bypass the case state machine.
5. Human promote path on `POST /v1/ops/trend/drafts/{id}/promote` (see below).
6. SPA: graph-missing banner on case chat; pending proposal + confirm; Ops trend promote control disabled without `backtest_job_id`.

### Durability ceiling

AgentRun and proposals stay SQLite under `INVESTIGATION_DATA_DIR` (same as today). Ingest remains correct if that DB is gone. Upgrade path if we run multiple investigation-agent replicas: shared Postgres. Not this spec.

## Human trend promote

`POST /v1/ops/trend/drafts/{draft_id}/promote`

**Still 409 `never_auto_promote` when any of:**

- caller is tick / `skip_llm` automation / missing actor
- `backtest_job_id` omitted
- `backtest_before_promote_gate(..., require_job=True)` fails
- graph neighborhood on the linked AgentRun is not `present`

**200 means:** set `gitops_ready=true` on the draft row. `status` stays `PENDING_VALIDATION` and `wasm_ready=false`. No live pack install. Existing GitOps/install/approve endpoints unchanged and remain the only path to live.

Tick must not pass actor + job to sneak through.

## Data flow

1. **Chat** — assemble snapshot → persist AgentRun → 200 with `agent_run_id`, `graph_missing`, claims.
2. **Shadow** — orchestrator already has `graph_context` from prime; after analyze, POST internal run (best-effort).
3. **Trend tick** — after evaluation/draft persist, POST internal run (best-effort) with entity snapshot (velocity present; graph present or missing).
4. **Lifecycle** — tool writes proposal + `agent_run_id`. Analyst confirm = PUT. Illegal transitions fail as today; proposal stays `pending`.
5. **Human promote** — analyst supplies `backtest_job_id`; API checks graph + gate; 200 GitOps-ready only.

## Errors

| Case | Response |
|------|----------|
| Graph missing on chat/Shadow | 200, `graph_missing=true`, banner |
| Graph missing on propose or human promote | `409 graph_required` |
| Investigation-agent down at ingest/tick | Parent still 200; warning log; no `agent_run_id` |
| Chat persist AgentRun fails | `503` — no un-audited copilot claim |
| Bad internal secret | `401 invalid_internal_secret` |
| Tick / no actor / no job on promote | `409 never_auto_promote` |
| Human promote, failed/missing backtest job | `409` with gate `blockers` |
| Illegal case transition on confirm | Same errors as today’s PUT |

## Testing

No live LLM in CI. Extend existing pytest files.

1. Internal POST persists; GET round-trips snapshot + claims + `source`.
2. Ingest still 200 when investigation-agent is down or times out.
3. Chat with missing graph returns `graph_missing=true` (not 409).
4. `propose_case_status` without graph → `409 graph_required`. Confirm via PUT creates audit + `case_history` row; proposal becomes `confirmed`.
5. Tick / missing `backtest_job_id` / missing actor on promote → `409 never_auto_promote`.
6. Human promote with succeeded backtest job + present graph → 200, `gitops_ready=true`, draft still `PENDING_VALIDATION`, `wasm_ready=false`, `agent_run_id` set. No live pack install.

Files: `test_agent_run_and_context.py`, `test_trend_agent_api.py`, `test_trend_watch_enqueue.py`, case-transition gate tests.

## Env

| Var | Default | Purpose |
|-----|---------|---------|
| `INVESTIGATION_INTERNAL_SECRET` | (existing) | Internal POST auth |
| `INVESTIGATION_AGENT_URL` | (existing where set) | Orchestrator / decision-api run ingest target |
| `AGENT_RUN_INGEST_TIMEOUT_SEC` | `2` | Fire-and-forget timeout |

## Non-goals

- New AgentRun service or SQLite→Postgres migration
- Auto-resolve cases; Shadow `FLAG`→`ALLOW`; auto-promote Wasm
- Changing decision-api allow/deny
- AGENTS.md / Cursor-rules developer program
- Shadow desktop mutating tools
- LIVE calibration claims
- Frontend-only tests (banner/button covered by API contracts in this spec)
