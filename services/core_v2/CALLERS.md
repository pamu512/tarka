# Remaining callers (quarantine)

Do not delete `services/core_v2` until this list is empty.

1. `docker-compose.streams-ai.yml` — builds this service as `core_api`
2. `services/ml_sidecar` — Redis `tarka:decisions_stream` / `tarka:decisions:stream`
3. `services/copilot_batch` — Postgres `audit_logs.raw_payload` whale scan
4. `scripts/test_sidecar_relay.py` — `/v1/decide` relay probe

Details: `DEPRECATED.md`, `docs/superpowers/specs/2026-07-25-core-v2-retirement-blockers.md`.
