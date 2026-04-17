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
| 2 | **Redis key versioning** | Set **`AGG_KEY_VERSION`** (alphanumeric / `._:-`) so keys become **`fraud:agg:{version}:{tenant}:{entity}:{metric}`**. **Empty** = legacy keys (no infix). **Rolling upgrade:** deploy writers + readers with the same value; replay/offline jobs must use the **same** env when rebuilding scratch Redis. Documented below § *Operator notes*. |
| 3 | **Offline replay** | **`scripts/replay/replay_aggregates.py`** reads JSONL; **`scripts/replay/export_audit_to_jsonl.py`** exports **`decision_audit`** rows to that shape (uses **`payload_snapshot.payload`** as **`fields`**). |
| 4 | **Parity proof** | **`scripts/replay/diff_aggregate_redis.py`** compares ZSETs between two Redis URLs. **CI:** [`.github/workflows/counter-parity-smoke.yml`](../../.github/workflows/counter-parity-smoke.yml) replays a fixture twice (with **`AGG_KEY_VERSION`**) and diffs. **Unit:** [`test_golden_counters.py`](../../services/decision-api/tests/test_golden_counters.py) includes a **~10×** event stress class. |
| 5 | **Ops API** | **`POST /v1/internal/counters/replay`** (token) for inline JSON; **`POST /v1/internal/counters/replay/from-audit`** loads **`decision_audit`** for **`tenant_id` + `entity_id`** (same token). |
| 6 | **Scheduled or runbook parity** | **Scheduled:** **`counter-parity-smoke`** workflow (weekly + manual). **Runbook:** § *Weekly parity runbook* below. |
| 7 | **Feature-service contract** | **`POST /v1/snapshot`** / **`POST /v1/velocity/query`** return **deterministic** multi-window counters when Redis is shared with decision-api (**[`roadmap-30-60-90.md`](./roadmap-30-60-90.md)** Day 60 acceptance). |
| 8 | **Rule-facing keys** | Normalized velocity keys (including **`distinct_session_id_24h`** when **`session_id`** present) are usable from rule packs / docs without guesswork. |

**Optional stretch (literal “10×” stress):** [`test_golden_counters.py`](../../services/decision-api/tests/test_golden_counters.py) **`TestGoldenEventCounts10xStress`** records **70** events (~10× the seven-event golden) and asserts counts/sums/distinct branches.

Until this section is satisfied, **`v1.2.0` stays in “building” mode** per [`RELEASE_SCHEDULE.md`](../../RELEASE_SCHEDULE.md).

### Operator notes (`AGG_KEY_VERSION`)

- **Purpose:** isolate a new key namespace when aggregate semantics change (migration) without deleting legacy keys immediately.
- **Set on:** decision-api, workers that call **`AggregateStore`**, **`replay_aggregates.py`**, and any offline job that must match production keys.
- **Manifest:** **`GET /v1/internal/counters/manifest`** echoes **`redis_key_version`** when the env var is valid.
- **Full playbook:** **[redis-agg-key-version-migration.md](./redis-agg-key-version-migration.md)** — big-bang, blue/green Redis, replay backfill, rollback, verification checklist.

### Audit → JSONL → scratch Redis (batch)

1. **Export** (Postgres example; set **`DATABASE_URL`** to sync driver if needed):

   `python scripts/replay/export_audit_to_jsonl.py --tenant-id YOUR_TENANT --entity-id YOUR_ENTITY --out /tmp/audit.jsonl --limit 5000`

2. **Replay** into DB 15 (set **`AGG_KEY_VERSION`** to match prod if versioned):

   `AGG_KEY_VERSION=prod_v1 python scripts/replay/replay_aggregates.py --input /tmp/audit.jsonl --redis-url redis://localhost:6379/15`

3. **Diff** prod vs scratch:

   `python scripts/replay/diff_aggregate_redis.py --left-url redis://prod:6379/0 --right-url redis://localhost:6379/15 --pattern 'fraud:agg*'`

### Weekly parity runbook (5 minutes)

1. Ensure **`redis` (pip)** and a local Redis (or tunnel to scratch).
2. `python scripts/replay/replay_aggregates.py --input scripts/replay/fixtures/parity_smoke.jsonl --redis-url redis://127.0.0.1:6379/14`
3. Same command with **`--redis-url`** `.../15` (same **`AGG_KEY_VERSION`** in env for both).
4. `python scripts/replay/diff_aggregate_redis.py --left-url .../14 --right-url .../15 --pattern 'fraud:agg*'` → exit **0**.

Or rely on the **Counter parity smoke** GitHub Action for the same invariant on schedule.