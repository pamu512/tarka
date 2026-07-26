# Fraud spine Phase 0 + Phase 1 core — design

## Goal

Unify the ingest → decide → act spine without consortium work: one ingest
contract, one feature catalog, one post-decision outcome handler, graph
freshness policy, and degraded-decision metrics. Scope is Phase 0 + Phase 1
core only (not main.py split / CQRS / frontend shrink).

## Decisions

| Topic | Choice |
|-------|--------|
| Public async ingest | event-ingest evaluate-shaped envelope; orchestrator `/v1/ingest` is an adapter |
| Shared helpers | `tarka_shared.ingest_contract_v1` for required identity fields |
| Feature catalog | Static table in decision-api; degrade tags always; fail-closed opt-in via env |
| Graph freshness | `warn` default; per-`event_type` `skip` / `fail_closed` via env |
| Outcome handler | `decision_outcome.schedule_decision_outcomes` owns log/webhook/metrics/publish/case |
| Case create | Opt-in (`CASE_CREATE_ON_DENY_REVIEW`); off by default (case-api role gate) |
| Legacy decision tree | Already retired from tree/CI; document as done |

## Recommended production env

```bash
FEATURE_CATALOG_FAIL_CLOSED_EVENT_TYPES=payment
GRAPH_RISK_FRESHNESS_DEFAULT_POLICY=warn
GRAPH_RISK_FRESHNESS_POLICY_BY_EVENT=payment:fail_closed,login:skip
CASE_CREATE_ON_DENY_REVIEW=true   # only with service-capable case_api auth
CASE_API_URL=https://case-api.internal
```

## Verify

```bash
pytest packages/shared-core/tests/test_ingest_contract_v1.py -q
pytest services/decision-api/tests/test_feature_catalog.py \
  services/decision-api/tests/test_decision_outcome.py \
  services/decision-api/tests/test_graph_risk_freshness.py \
  services/decision-api/tests/test_rules_batch.py -q
```

## Out of scope (later phases)

- Split `main.py` evaluate into pipeline packages
- CQRS hot/cold path
- Frontend client shrink
- Full production auth/idempotency CI checklist expansion
