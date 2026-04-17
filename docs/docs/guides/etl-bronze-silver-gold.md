# ETL tiers: Bronze, Silver, Gold (Tarka mapping)

**Purpose:** Align the classic **Bronze / Silver / Gold** data-quality mental model with what ships **today** in-repo, and what is **roadmapped** (warehouse, materialized facts). Part of **v1.2.5 Epic E2**.

---

## Physical mapping (current)

| Tier | What it is in Tarka today | Storage / motion |
|------|---------------------------|------------------|
| **Bronze** | **Immutable raw event** as accepted by producers | NATS JetStream payload on `fraud.events.{tenant}.{event_type}` (see `event-ingest`); optional **DLQ** subject `fraud.events.dlq` for poison / non-retryable evaluate failures (see `INGEST_DLQ_*` env). |
| **Silver** | **Canonical evaluate input** — same fields Decision API persists | Decision API `POST /v1/decisions/evaluate` body; **Postgres** `audit` rows (`payload_snapshot`, `inference_context`, tags, rule_hits). Treat audit as the **system-of-record “silver”** slice for fraud decisions until a separate warehouse exists. |
| **Gold** | **Aggregates & reporting features** | Redis velocity / aggregates (`agg_store`), counter manifest + replay scripts, analytics sink path when enabled — **not** a single SQL table today. |

---

## Promotion gates (conceptual)

| Promotion | Checks |
|-----------|--------|
| Bronze → stream | JSON parseable; optional **contract** envelope (E1); reject/quarantine at HTTP edge with `reason_codes`. |
| Silver (evaluate) | Pydantic + rules; optional OPA/ML/graph timeouts (see **#32** `step_trace`). |
| Gold (features) | Null-safe keys, enum domains for `event_type`, numeric ranges for amounts — automated in **`scripts/etl/check_silver_features.py`** for batch files / exports. |

---

## DLQ & replay

- **DLQ publish:** when `INGEST_DLQ_PUBLISH_ON_EVALUATE_4XX=true`, the NATS consumer **acks** the bad message and **republishes** a DLQ envelope to `fraud.events.dlq` (same stream wildcard `fraud.events.>`).
- **Replay stub:** `python scripts/etl/replay_dlq.py --max 100 --dry-run` — pulls from DLQ and optionally POSTs back to evaluate (use with care in non-prod).

---

## Related

- [Ingest hardening & replay](./ingest-replay-onboarding.md)
- [Late arrival & watermarks](./late-arrival-watermarks.md) (Epic **E3**)
- [v1.2.5 execution backlog](./v1.2.5-execution-backlog-resiliency-etl-rules.md)
