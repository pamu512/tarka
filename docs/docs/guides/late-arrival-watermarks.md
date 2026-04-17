# Late arrival, event time, and watermarks (v1.2.5 Epic E3)

**Purpose:** Explain how **business time** relates to **ingest time** for Redis velocity counters, how **offline replay** stays aligned with **online** `AggregateStore`, and what a **watermark** means in this stack.

---

## Two clocks

| Concept | Meaning in Tarka | Typical source |
|--------|------------------|----------------|
| **Event time** (business time) | When the fraud-relevant activity *happened* from the product’s perspective | Client clock (`metadata.event_time`), backfilled batch jobs |
| **Ingest time** (processing time) | When Decision API **accepted** the evaluate request | Server wall clock at `POST /v1/decisions/evaluate` |

**Redis velocity** (`fraud:agg:*` sorted sets) stores each member with a **score = Unix timestamp**. Sliding windows (`event_count_1h`, `sum_amount_24h`, …) use **`time.time()`** as “now” when **reading** counts, and the **same timestamp** for **writes** unless you pass an explicit event time.

---

## How evaluate picks the aggregate timestamp

On each successful evaluate, Decision API calls `AggregateStore.record_event(..., ts=...)`.

- If **`metadata.event_time`**, **`metadata.event_ts`**, or **`metadata.occurred_at`** is set to a parseable **ISO-8601** string or **Unix seconds** (numeric or string), that value is used as the ZSET score (**business time**).
- The same keys are read from **`payload`** if absent from metadata (legacy / misplaced fields).
- If none are present, **`ts` defaults to wall-clock ingest time** (existing behavior).

Parsing is implemented in **`services/shared/event_time.py`** (`event_time_unix_for_evaluate`).

**Late-arriving events** (e.g. mobile offline queue) therefore land in the **correct historical window** when clients send **`metadata.event_time`**, instead of all stacking at backfill time.

---

## Watermark (operator meaning)

There is **no separate watermark table** in-repo today. The practical **processing-time watermark** is:

- **Latest ingest** you trust for a stream (NATS consumer lag, `created_at` on audit rows), and  
- **Optional business-time cap**: events with **`metadata.event_time` older than (now − max lateness)** may be **rejected or quarantined** by *your* gateway or a future policy — not enforced in Decision API v1.2.5.

For **analytics** and **batch replay**, treat **audit `created_at`** as ingest time and **`metadata.event_time`** (when present) as the logical time used for aggregates.

---

## Feature service and parity

**`POST /v1/snapshot`** and **`POST /v1/velocity/query`** in feature-service read the **same Redis keys** as Decision API. They do **not** re-write aggregates.

Parity rules:

1. **Same Redis URL** as Decision API (`FEATURE_SERVICE_REDIS_URL` / `REDIS_URL`).
2. **Same `AGG_KEY_VERSION`** when keys are versioned.
3. For **offline replay**, use timestamps consistent with online writes — see below.

---

## Offline replay alignment (E3.2)

1. **`scripts/replay/export_audit_to_jsonl.py`** emits each line with:
   - **`ts`** = logical event time from **`payload_snapshot`** when **`metadata.event_time`** / **`payload.event_time`**-style fields exist, else **`created_at`** epoch.
   - Optional **`metadata`** echo so JSONL carries the same hints as audit.

2. **`scripts/replay/replay_aggregates.py`** uses per-row **`ts`** when present; if absent, it derives a timestamp from **`metadata` + `fields`** via **`event_time_unix_for_evaluate`** (same rules as evaluate).

Replaying that JSONL into scratch Redis with the **same `AGG_KEY_VERSION`** as production reproduces **`fraud:agg:*`** for parity checks (`diff_aggregate_redis.py`).

---

## Related

- [Ingest hardening & replay](./ingest-replay-onboarding.md) — ingest idempotency and batch replay  
- [Counter replay parity](./counter-replay-parity.md) — manifest, CI, ops APIs  
- [ETL Bronze / Silver / Gold](./etl-bronze-silver-gold.md) — where audit and aggregates sit in the tier model  
- [v1.2.5 execution backlog](./v1.2.5-execution-backlog-resiliency-etl-rules.md) — Epic **E3** status
