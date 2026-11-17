# Velocity contract: `anumana:velocity` vs `AggregateStore`

Status: **documented contract** (2026-11-17). Two Redis-backed velocity namespaces
exist deliberately today; this page is the single place that says who writes what,
who reads what, and the plan for folding them. Prune-plan context: `tarka-prune-plan.md`
item 3.1 (workspace copy), owner decision 2026-11-17: document now, fold later.

## The two namespaces

| | `AggregateStore` (canonical) | `anumana:velocity` (parallel) |
|---|---|---|
| Implementation | `fraud_aggregates.AggregateStore` (feature-service) | `services/orchestrator/anumana_velocity.py` |
| Key prefix | shared with decision-api aggregates | `anumana:velocity` (override: `ANUMANA_VELOCITY_KEY_PREFIX`) |
| Writer | feature-service (signal-api mount) | orchestrator ingest path + outbox `VELOCITY_UPDATE` workers |
| Reader | feature-service `/v1/velocity/query`; decision-api enrichment | decision-api evaluate path via `decision_api/anumana_signals.py` (`ANUMANA_VEL_PREFIX`); anumana duck-sink telemetry |
| Consumers | decision enrichment (product surface) | decision enrichment (device/tenant counters) + telemetry analytics |

## Why both exist

`AggregateStore` is the product velocity surface (feature snapshots, parity-fixture
pinned by OSS #48). The anumana plane grew on the ingest side for device/tenant
counters and telemetry; decision-api's evaluate path reads it directly
(`anumana_signals.py`), which makes it a live cross-service contract rather than
dead duplication.

## Contract rules while both exist

1. Orchestrator owns writes to `anumana:velocity:*`; decision-api only reads.
2. Key shape and counter semantics must not change without updating
   `services/decision-api/tests/test_anumana_signals.py` (pins the prefix) and
   `services/orchestrator/tests/test_velocity_update_handler_gate.py` (pins the
   commands).
3. No new reader may be added to either namespace outside this page's table.

## Fold-later plan

If the counter semantics match (windowed counts + amounts), fold the anumana writes
into `AggregateStore` and swap decision-api's reader. Gate: extend the OSS #48
parity fixture (`packages/feature-service/src/feature_service/main.py:152`) to cover
the anumana keys first, then migrate behind it. Until then: both namespaces stay,
this page is the contract.
