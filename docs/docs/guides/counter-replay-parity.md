# Counter replay and online/offline parity (v1.2.0 target)

**Problem:** Vendors win on **deterministic counters** with **replay** from audit streams and **shadow** parity checks. Tarka has Redis-backed aggregates in `decision_api.aggregates` but lacks a first-class **offline replay job** and **counter versioning**.

## Engineering plan (ship by ~2026-05-30)

1. **Counter manifest** — YAML/JSON declaring named counters (window, key fields, version). Store version in Redis key prefix or sidecar metadata.
2. **Replay worker** — Consume `decision_audit` (or exported event JSONL), rebuild aggregates in a **scratch Redis DB** (or isolated key namespace), diff against production snapshot for sampled entities.
3. **CI gate** — Golden fixture: N events → expected `event_count_1h` for a fixed clock (injectable `TimeProvider` in tests).
4. **API** — Optional `POST /v1/internal/counters/replay` (admin-only) for ops; default remains batch job in `scripts/` or `services/event-ingest`.

## Dependencies

- Alembic audit schema stable (`decision_audit`).
- Clock injection in `AggregateStore` for tests (small refactor).

## Status

**Design + roadmap** for **v1.2.0**; implementation tracks **`roadmap-30-60-90.md`** Day 60 scope. This document is the acceptance checklist for “counter maturity” in the competitive matrix.

**In repo today:**

- [`scripts/replay/replay_aggregates.py`](../../../scripts/replay/replay_aggregates.py) — JSONL → **`AggregateStore`** on a scratch Redis DB.
- [`scripts/replay/diff_aggregate_redis.py`](../../../scripts/replay/diff_aggregate_redis.py) — compare **`fraud:agg*`** ZSETs between two Redis URLs (prod vs scratch).
- **CI** — [`test_golden_counters.py`](../../../services/decision-api/tests/test_golden_counters.py) (decision-api pytest) locks **`event_count_1h`**, sums, and distinct counts under a **fixed injectable clock** on `AggregateStore`.
