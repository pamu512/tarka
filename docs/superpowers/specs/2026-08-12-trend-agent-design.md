# Trend agent (Omniscient track C)

**Status:** Landed in OSS analytics (2026-08-12)  
**Code:** `services/analytics/src/analytics/trend_agent.py`, `trend_rag.py`, `trend_store.py`  
**Postgres:** `migrations/20260603_003_trend_agent_persistence.sql` (prod); default offline store is SQLite under `TREND_AGENT_DATA_DIR`.

## Role

Automated **forensic statistician** for multi-window velocity deviations. Not an autonomous decider:

- Seasonal / HIL-covered spikes → `RESOLVED_SYSTEMIC` (no LLM, no draft promotion)
- Unmanaged `|Z| > 4` → triage ticket + draft rule `PENDING_VALIDATION` only
- LLM timeout / unavailable → fail-closed escalate (never clear)

## Contract

1. **RAG matrix is the source of truth** (`compile_rag_matrix` → JSON user message).  
2. **LLM is optional and provider-agnostic** — any OpenAI-compatible `POST {base}/chat/completions` (OpenAI, Azure OpenAI, vLLM, Groq, Ollama `/v1`, etc.).  
3. Inject a custom `LlmClient` if you are not HTTP OpenAI-shaped.

## Loop

1. `compile_rag_matrix(...)` from caller-supplied window stats  
2. `try_resolve_systemic(...)` pre-LLM gate  
3. Optional chat model → `TrendDecisionEnvelope`  
4. Persist triage + `PENDING_VALIDATION` drafts via `trend_store`  
5. `apply_feedback_override(...)` writes HIL rows for the next iteration

## Entrypoint

```python
import asyncio
from analytics.trend_agent import run_trend_evaluation

asyncio.run(run_trend_evaluation(
    "tenant-1",
    "entity-42",
    window_rows=[...],
    skip_llm=True,  # or TREND_AGENT_SKIP_LLM=1
))
```

HTTP (decision-api):

- `POST /v1/ops/trend/evaluate` — run loop (drafts `wasm_ready=false`)
- `GET /v1/ops/trend/drafts?tenant_id=`
- `POST /v1/ops/trend/drafts/{id}/reject`
- `POST /v1/ops/trend/drafts/{id}/promote` → **409 never_auto_promote**
- `POST /v1/ops/trend/hil-override`

Investigation chat tool: `evaluate_entity_trend` (requires explicit `window_rows`).

## Env

| Var | Purpose |
|-----|---------|
| `TREND_AGENT_DATA_DIR` | SQLite directory (default `./var/trend-agent`) |
| `TREND_AGENT_SKIP_LLM` | Skip LLM; policy escalate when a model would be required |
| `TREND_AGENT_LLM_BASE_URL` / `OPENAI_BASE_URL` | OpenAI-compatible API base (default `https://api.openai.com/v1`) |
| `TREND_AGENT_LLM_MODEL` / `OPENAI_MODEL` | Model id |
| `TREND_AGENT_LLM_API_KEY` / `OPENAI_API_KEY` | Bearer token (optional for local servers) |
| `OLLAMA_OPENAI_BASE_URL` | Optional Ollama OpenAI shim, e.g. `http://127.0.0.1:11434/v1` |

See also: [omniscient AgentRun design](./2026-08-11-omniscient-agent-run-design.md).
