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

---

## Epic C completion (“10x” bar)

**“10x”** here means **full Epic C maturity**, not a partial increment: counters are **versioned**, **replayable**, **parity-checked**, and **operationally repeatable**—the same bar a serious vendor would use before calling the velocity platform “done.”

**Required before `v1.2.0` is allowed to ship** (tag + GitHub release + “GA” messaging):

| # | Criterion | Notes |
|---|-----------|--------|
| 1 | **Manifest + keys** | Counter manifest v1 lists every **`compute_features`** output; **`GET /v1/internal/counters/manifest`** reflects env (**`AGG_KEY_VERSION`**) when set. |
| 2 | **Redis key versioning** | **`AGG_KEY_VERSION`** documented for operators; migration path from empty version → versioned keys (no silent split-brain). |
| 3 | **Offline replay** | JSONL / **`replay_aggregates.py`** path exercised in docs; optional **audit-export → replay** batch documented or implemented. |
| 4 | **Parity proof** | **`diff_aggregate_redis.py`** (or equivalent) used in a **documented** prod-vs-scratch check; CI golden tests stay green. |
| 5 | **Ops API** | **`POST /v1/internal/counters/replay`** remains token-gated; behavior matches manifest for sampled workloads. |
| 6 | **Scheduled or runbook parity** | Either a **scheduled** job/workflow for parity smoke **or** a short **runbook** (copy-paste) the team agrees is “weekly bar” enough. |
| 7 | **Feature-service contract** | **`POST /v1/snapshot`** / **`POST /v1/velocity/query`** return **deterministic** multi-window counters when Redis is shared with decision-api (**[`roadmap-30-60-90.md`](./roadmap-30-60-90.md)** Day 60 acceptance). |
| 8 | **Rule-facing keys** | Normalized velocity keys (including **`distinct_session_id_24h`** when **`session_id`** present) are usable from rule packs / docs without guesswork. |

**Optional stretch (literal “10×” stress):** extend golden or replay fixtures to **~10×** the default event count (e.g. order of magnitude more ZSET members) to catch performance or correctness drift—only if you want an explicit load-ish gate on top of the checklist above.

Until this section is satisfied, **`v1.2.0` stays in “building” mode** per [`RELEASE_SCHEDULE.md`](../../RELEASE_SCHEDULE.md).