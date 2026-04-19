# Late arrival, event time, and watermarks (v1.2.5 Epic E3)

## Two clocks

| Concept | In Tarka | Typical source |
|--------|----------|----------------|
| **Event time** | When the activity happened for the product | `metadata.event_time`, backfill jobs |
| **Ingest time** | When Decision API accepted `POST /v1/decisions/evaluate` | Server wall clock |

Redis velocity (`fraud:agg:*`) uses **ZSET scores = Unix time**. `AggregateStore.record_event` uses **event time** when `metadata.event_time` / `event_ts` / `occurred_at` (or the same keys on `payload`) parse successfully; otherwise **ingest time**.

Parsing lives in **`services/shared/event_time.py`**.

## Watermarks

There is no separate watermark table. **Processing lag** is visible via NATS consumer metrics and audit `created_at`. You may enforce a **max lateness** at your gateway (reject `metadata.event_time` older than now − window).

## Offline replay

**`scripts/replay/export_audit_to_jsonl.py`** prefers logical time from `payload_snapshot` for **`ts`** when available. **`scripts/replay/replay_aggregates.py`** uses **`ts`** or derives time consistently.

## Related

- [Counter replay parity](./counter-replay-parity.md)
- [Ingest hardening & replay](./ingest-replay-onboarding.md)
