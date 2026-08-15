# Ingest unify (adapter + one server + side-effect bus)

**Date:** 2026-08-15  
**Status:** Implemented  
**Related:** [ingest-contract-v1](../../docs/guides/ingest-contract-v1.md)

## Goal

One inward envelope (contract v1), one `/v1/events` server (Python data-plane), and the same audit + graph + velocity commit after evaluate on both sync and async paths.

## Sequence

1. Orchestrator `POST /v1/ingest` still accepts `TransactionSchema`. Outbox `GRAPH_INGEST` carries `event` (contract v1). Handler prefers `event`; envelope remains for in-flight rows.
2. Python event-ingest is the only accept+consume path. Rust does not register `/v1/events` or spawn an evaluate consumer. `POST /v1/ingest/dynamic` lives on Python.
3. After evaluate 2xx, the Python consumer POSTs `/v1/internal/ingest-side-effects` when `ORCHESTRATOR_URL` is set. 5xx → NAK. 4xx → ack. Unset URL → ack and skip (streaming compose without orchestrator).

## Not in scope

Shadow/trend/AgentRun on the async path. Batch-ingest through evaluate. Browser `POST /ingest` graph writes. Decision-api writing outbox.
