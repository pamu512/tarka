# Fraud spine Phase 2 — Wave A + B design

Approved 2026-07-29. Scope: leftovers (A) + CQRS-ish lag budgets (B).

## Wave A — Leftovers

1. **Prod presets** — `docker-compose.production-hardening.yml` + env examples set
   `FEATURE_CATALOG_FAIL_CLOSED_EVENT_TYPES=payment`,
   `GRAPH_RISK_FRESHNESS_POLICY_BY_EVENT=payment:fail_closed,login:skip`,
   and production profile knobs on core-api / decision path.
2. **Orchestrator ingest map** — after `map_tx_to_evaluate_request`, validate with
   `tarka_shared.ingest_contract_v1` so TransactionSchema adapters cannot fork identity fields.
3. **Enrichment extract** — move graph/feature wrapped fetchers into
   `decision_api/evaluate/enrichment.py` with a bound runtime (circuits/metrics);
   main keeps aliases for tests/pipeline.

## Wave B — CQRS lag budgets

- Sync evaluate may **read** async Redis OSINT cache; it must not wait on enrichment workers.
- Cache blobs carry `updated_at` (integration-ingress). If older than
  `ASYNC_ENRICH_MAX_AGE_MINUTES` (default 60), add degrade tag `async_enrich:stale` + metric;
  still merge features (fail soft).
- Document sync vs async ownership in this spec and a short ops note under guides.

## Out of scope (later waves)

Policy packing, enforcement adapters, frontend mockData shrink.
