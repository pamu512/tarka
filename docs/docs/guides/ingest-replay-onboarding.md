# Ingest hardening, SDKs, and offline replay (onboarding)

This guide ties together **high-volume ingestion**, **client SDKs**, **idempotency**, **consumer observability**, and the **v1.2 replay** script.

## Two ways to score an event

| Path | When to use | Entry point |
|------|-------------|-------------|
| **Synchronous** | You need `trace_id`, decision, and `inference_context` in the same HTTP round-trip | **Decision API** `POST /v1/decisions/evaluate` |
| **Asynchronous** | High write volume; scoring can lag slightly behind accept | **Event ingest** `POST /v1/events` → NATS → worker → Decision API |

Default compose port for event-ingest (full/streaming profile) is **8007** (`deploy/docker-compose.yml`).

## Python SDK

Install from `packages/fraud-sdk-python` (`pip install -e .`).

```python
from fraud_stack_sdk import DecisionClient, EventIngestClient

decision = DecisionClient("http://localhost:8000", api_key="...")
ingest = EventIngestClient("http://localhost:8007", api_key="...")

# Sync evaluate
out = decision.evaluate("tenant", "login", "user-1", payload={"ip": "1.2.3.4"})

# Async fire-and-forget (returns ingest_id; scoring happens in the worker)
ingest.send_event("tenant", "login", "user-1", payload={"ip": "1.2.3.4"})
```

- **`EventIngestClient.send_event` / `send_batch`** — REST only; optional **`idempotency_key=`** sends the `Idempotency-Key` header for **`POST /v1/events`** and **`POST /v1/events/batch`** (see below).
- **`send_event_async` / `send_batch_async`** — same for async `httpx` callers.

## TypeScript SDK

Package: `packages/fraud-sdk-typescript` (`npm run build`).

- **`DecisionClient`** — `evaluate()`, attestation helpers, audit fetch.
- **`EventIngestClient`** — `sendEvent()`, `sendBatch()`; optional **`idempotencyKey`** on both.

## Ingest hardening (event-ingest service)

### Idempotency (single event)

When **`REDIS_URL`** is set, **`POST /v1/events`** deduplicates on:

- HTTP header **`Idempotency-Key`** (or **`idempotency-key`**), or  
- **`metadata.idempotency_key`** on the JSON body.

Same tenant + same key within the TTL returns the **first** response with **`duplicate: true`** (no second NATS publish). Configure TTL with **`IDEMPOTENCY_TTL_SECONDS`** (default **86400**). Key prefix in Redis: **`ingest:idemp:`** (override with **`IDEMPOTENCY_KEY_PREFIX`**).

### Contract-first envelope (v1, v1.2.5)

**`INGEST_ENVELOPE_MODE`** (default **`optional`**):

- **`optional`**: accept either **legacy flat** body `{ tenant_id, event_type, entity_id, ... }` or **v1 envelope**:
  ```json
  { "schema_version": "1", "event": { "tenant_id": "...", "event_type": "login", "entity_id": "...", "payload": {} } }
  ```
- **`required`**: only the envelope form above is accepted.

**`INGEST_REQUIRE_IDEMPOTENCY_KEY`** (default **`false`**): when **`true`**, **`POST /v1/events`** returns **`422`** with `reason_codes: ["ingest_idempotency_key_required"]` if the **`Idempotency-Key`** header is missing (high-volume retry safety).

Malformed `event_type` (not in Decision API enum) returns **`422`** with `reason_codes: ["ingest_event_type_invalid"]`.

Prometheus: **`ingest_contract_reject_total`** and **`ingest_contract_reject_total_<reason>`**.

**`GET /v1/ingest/stats`** (authenticated like other ingest routes): in-process totals of contract rejects by `reason_codes` since process start.

**DLQ (optional):** set **`INGEST_DLQ_PUBLISH_ON_EVALUATE_4XX=true`** so the NATS→evaluate worker **acks** 4xx evaluates and publishes a JSON envelope to **`INGEST_DLQ_SUBJECT`** (default `fraud.events.dlq`, same stream `fraud.events.>`). Replay: **`scripts/etl/replay_dlq.py`**.

See also: [v1.2.5 execution backlog](./v1.2.5-execution-backlog-resiliency-etl-rules.md) (Epic **E1**). [Bronze/Silver/Gold](./etl-bronze-silver-gold.md) (Epic **E2**).

### Idempotency (batch)

**`POST /v1/events/batch`** supports a **whole-batch** key: header **`Idempotency-Key`** or JSON field **`idempotency_key`** (sibling of **`events`**). The cache fingerprint is **`SHA256(idem + canonical JSON of events)`** — same key with different event payloads publishes again. Response may include **`duplicate: true`** on replay. Per-row idempotency is not applied inside a batch; use single-event **`POST /v1/events`** for row-level keys.

### Consumer metrics

The NATS → Decision worker increments Prometheus counters (exposed on **`/metrics`** with other service metrics):

- **`ingest_consumer_evaluate_2xx_total`** — evaluate returned &lt; 400  
- **`ingest_consumer_evaluate_4xx_total`** — evaluate 4xx (message **acked**; fix payload/rules)  
- **`ingest_consumer_evaluate_5xx_total`** — evaluate 5xx (**NAK** + retry)  
- **`ingest_consumer_json_decode_errors_total`** — invalid JSON on stream  
- **`ingest_consumer_nats_ack_total`** / **`ingest_consumer_nats_nak_total`** — JetStream disposition  

### Health

**`GET /v1/health`** includes **`redis_configured`** and **`redis_ok`** (null when Redis is not configured).

### DLQ (optional, Epic E2)

Set **`INGEST_DLQ_SUBJECT`** (e.g. **`fraud.events.dlq`**) and **`INGEST_DLQ_PUBLISH_ON_EVALUATE_4XX=true`** so the NATS→Decision worker **acks** 4xx evaluates and publishes a structured envelope to the DLQ subject (must match the JetStream wildcard, typically **`fraud.events.>`**). Replay: **`scripts/etl/replay_dlq.py`** (`--dry-run` first).

### Silver export checks

**`scripts/etl/check_silver_features.py`** — validates JSONL rows for **`tenant_id`**, **`entity_id`**, **`event_type`** enum, numeric **`amount`**. See **[etl-bronze-silver-gold.md](./etl-bronze-silver-gold.md)**.

## Offline aggregate replay (v1.2)

Use a **dedicated Redis database** (e.g. `redis://localhost:6379/15`) so you do not overwrite production keys.

```bash
python scripts/replay/replay_aggregates.py --input export.jsonl --redis-url redis://localhost:6379/15 --dry-run
python scripts/replay/replay_aggregates.py --input export.jsonl --redis-url redis://localhost:6379/15
python scripts/replay/replay_aggregates.py --manifest-info
```

**Counter manifest:** `replay_aggregates.py --manifest-info` prints the bundled version; **Decision API** exposes the same JSON at **`GET /v1/internal/counters/manifest`**. For small JSON batches (no file), **`POST /v1/internal/counters/replay`** writes to a scratch Redis URL when **`COUNTER_REPLAY_TOKEN`** is set and you send header **`X-Tarka-Counter-Replay-Token`**.

JSONL rows should include **`tenant_id`**, **`entity_id`**, and either **`fields`** (object) or **`payload`** / **`request_body`** for aggregate dimensions. Optional **`event_id`**, **`trace_id`**, or **`ts`** (unix) per line.

See **`scripts/replay/README.md`** and **[counter-replay-parity.md](./counter-replay-parity.md)** for the full v1.2 acceptance picture.

### Automated prod vs scratch diff

After replay into a scratch DB, compare sorted sets:

```bash
pip install redis   # if needed
python scripts/replay/diff_aggregate_redis.py \
  --left-url redis://localhost:6379/0 \
  --right-url redis://localhost:6379/15 \
  --pattern 'fraud:agg*'
```

Exit code **0** means every **`fraud:agg*`** ZSET present on either side matches member/score pairs; **1** reports missing keys or mismatches.

## CI golden counter tests

**`services/decision-api/tests/test_golden_counters.py`** runs in normal **decision-api** CI. It uses **`AggregateStore(..., clock=fixed)`** and deterministic timestamps so **`event_count_1h`**, **`sum_amount_1h`**, and **`distinct_ip_address_24h`** match expected values without flakiness.

## Related docs

- **[sandbox-five-minute.md](./sandbox-five-minute.md)** — quick evaluate + UI path  
- **[release-gap-closure-schedule.md](./release-gap-closure-schedule.md)** — what ships 4/30 vs 5/30  
