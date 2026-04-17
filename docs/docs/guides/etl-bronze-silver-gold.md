# ETL tiers: Bronze, Silver, Gold (Tarka mapping)

**Purpose:** Map the **Bronze / Silver / Gold** mental model to what ships in-repo (v1.2.5 Epic **E2**).

---

## Physical mapping (current)

| Tier | Meaning | Storage / motion |
|------|---------|------------------|
| **Bronze** | Immutable raw event as accepted | NATS JetStream on `fraud.events.{tenant}.{event_type}`; optional **DLQ** subject (see below). |
| **Silver** | Canonical evaluate input / audit slice | Decision API evaluate body; Postgres **`decision_audit`** (`payload_snapshot`, tags, `inference_context`). |
| **Gold** | Aggregates & reporting features | Redis velocity (`fraud:agg:*`), counter manifest + replay scripts. |

---

## DLQ (dead-letter queue)

When **`INGEST_DLQ_PUBLISH_ON_EVALUATE_4XX=true`** and **`INGEST_DLQ_SUBJECT`** is set (default in docs: **`fraud.events.dlq`**), the NATS→evaluate worker **acks** 4xx responses and publishes a JSON envelope to that subject. The stream must already cover **`fraud.events.>`** (same as primary ingest).

Replay (careful in non-prod): **`python scripts/etl/replay_dlq.py --max 10 --dry-run`**.

---

## Silver quality gate (batch)

**`scripts/etl/check_silver_features.py`** validates JSONL exports (tenant/entity/event_type/amount) for CI or manual QA.

---

## Related

- [Ingest hardening & replay](./ingest-replay-onboarding.md)
