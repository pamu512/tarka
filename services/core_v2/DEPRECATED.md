# Deprecated — quarantine: streams-ai only

`core_v2` is a legacy **speed-layer** FastAPI (Rust FFI + Redis streams) that
duplicates evaluate surfaces owned by **decision-api** (via core-api
`/decisions`).

- **Default local stack:** repo-root `docker-compose.yml` → Lite (`core-api`).
  **`core_v2` is not on that path.**
- **Only remaining compose entry:** `docker-compose.streams-ai.yml`
  (Redis stream consumers / ML sidecar / batch copilot that still expect this API).
- **Production evaluate:** `POST …/decisions/v1/decisions/evaluate` or
  orchestrator ingest (`RULE_EVAL_BACKEND=decision_api`).
- Do not add product features here.

## Remaining callers (do not half-migrate)

| Caller | Contract still owned by `core_v2` | Blocker |
|--------|-----------------------------------|---------|
| `docker-compose.streams-ai.yml` → `core_api` | Builds `services/core_v2/Dockerfile`, exposes `:8000` `/v1/decide` | No decision-api substitute wired into this compose file yet |
| `services/ml_sidecar` | Consumes Redis stream `tarka:decisions_stream` (+ pub/sub `tarka:decisions:stream`) that `core_v2` publishes after decide | decision-api / core-api do not XADD this stream today |
| `services/copilot_batch` | Reads Postgres `audit_logs` with `raw_payload` shape matching `core_v2.db.AuditLog` | Requires schema + writer parity before pointing `DATABASE_URL` at decision-api audit |
| `scripts/test_sidecar_relay.py` | Integration probe: `POST /v1/decide` → stream → ml_sidecar | Tied to core_v2 decide + stream contract |

**Removal gate:** retire this directory and `docker-compose.streams-ai.yml` only after
the table above is empty (rg -n 'core_v2|tarka:decisions_stream|/v1/decide').

This PR intentionally **does not** force a half migration of streams-ai onto
decision-api; contracts would break.
