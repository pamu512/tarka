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

Implementation tracks `**roadmap-30-60-90.md`** Day 60 scope. This document is the acceptance checklist for “counter maturity” in the competitive matrix.

**In repo today:**

- **Counter manifest (v1)** — `[services/decision-api/src/decision_api/data/counter_manifest_v1.json](../../../services/decision-api/src/decision_api/data/counter_manifest_v1.json)` lists `**compute_features`** output names + windows; `**GET /v1/internal/counters/manifest**` exposes it; CI `[test_counter_manifest.py](../../../services/decision-api/tests/test_counter_manifest.py)` asserts keys match `**AggregateStore.compute_features**` when all branches apply.
- **Ops replay API** — `**POST /v1/internal/counters/replay`** (requires env `**COUNTER_REPLAY_TOKEN**` and header `**X-Tarka-Counter-Replay-Token**`) replays a JSON event list into a **scratch** Redis URL. Disabled until the token is set.
- `[scripts/replay/replay_aggregates.py](../../../scripts/replay/replay_aggregates.py)` — JSONL → `**AggregateStore`** on a scratch Redis DB; `**--manifest-info**` prints manifest version.
- `[scripts/replay/diff_aggregate_redis.py](../../../scripts/replay/diff_aggregate_redis.py)` — compare `**fraud:agg***` ZSETs between two Redis URLs (prod vs scratch).
- **CI** — `[test_golden_counters.py](../../../services/decision-api/tests/test_golden_counters.py)` locks `**event_count_1h`**, sums, and distinct counts under a **fixed injectable clock** on `AggregateStore`.

**Still open (v1.2):** counter manifest YAML versioning in Redis key prefix, optional `**POST /v1/internal/counters/replay`** batch from audit export (today: JSON body only), scheduled parity job.

**Epic C increment (trunk):** `**distinct_session_id_24h**` is part of **`AggregateStore.compute_features`**, the v1 counter manifest, and **`normalized_velocity_key_names()`** — use payload / evaluate fields that include **`session_id`** so the distinct branch runs (same pattern as **`device_id`** / **`ip_address`**).