# Tombstone / quarantine map — core_v2 retirement (prep only)

Status: **not retired**. Forced migration of `docker-compose.streams-ai.yml` would
break Redis-stream and `audit_logs` contracts still owned by `services/core_v2`.

See [`services/core_v2/DEPRECATED.md`](../../services/core_v2/DEPRECATED.md) for the
caller table and removal gate.

## Safe next steps (separate PRs)

1. Teach decision-api or core-api to optionally `XADD` `tarka:decisions_stream` with
   the ml_sidecar payload shape (compat feature flag).
2. Point `copilot_batch` at decision-api / orchestrator audit schema with an adapter
   for `raw_payload.amount` whale scans.
3. Rewrite `docker-compose.streams-ai.yml` to use core-api + the flag, then delete
   `services/core_v2`.
