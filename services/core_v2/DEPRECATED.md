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

Removal: drop `docker-compose.streams-ai.yml` services + this directory once
stream consumers point at decision-api audit / NATS.
