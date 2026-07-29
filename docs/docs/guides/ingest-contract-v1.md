# Ingest Contract v1

One public async ingest semantics layer. Adapters may exist; required identity
fields and error codes must not fork.

## Canonical envelope (async / evaluate-shaped)

Used by **event-ingest** `POST /v1/events` (and batch) and by **decision-api**
`POST /v1/decisions/evaluate`.

| Field | Required | Notes |
|-------|----------|--------|
| `tenant_id` | yes | Non-empty string |
| `entity_id` | yes | Non-empty string |
| `event_type` | yes | `login` \| `payment` \| `signup` \| `device` \| `session` \| `custom` |
| `session_id` | no | |
| `payload` | no | Object; event-specific attributes |
| `device_context` | no | `{ device_id, platform, signals, … }` |
| `metadata` | no | Object; may carry `idempotency_key`, `etl_batch_id`, … |
| `agent_context` | no | Agent / MCP session envelope |

Optional **v1 wire envelope** (event-ingest only):

```json
{
  "schema_version": "1",
  "etl_batch_id": "batch-…",
  "event": { "tenant_id": "…", "entity_id": "…", "event_type": "payment", "payload": {} }
}
```

Shared field checks live in `packages/shared-core/tarka_shared/ingest_contract_v1.py`.
Event-ingest unwrap + full parse: `services/event-ingest/src/event_ingest/ingest_contract.py`.

## Adapter: orchestrator `POST /v1/ingest`

Orchestrator accepts **`TransactionSchema`** (`entity_id` UUID, `amount`, `timestamp`,
`metadata`, optional `country`) for policy + outbox side-effects. That path is **not**
a second public fraud envelope — it must map into evaluate-shaped fields before
calling decision-api (tenant / event_type / entity / payload).

| TransactionSchema | Evaluate / async ingest |
|-------------------|-------------------------|
| `entity_id` (UUID) | `entity_id` (string) |
| `amount` | `payload.amount` |
| `timestamp` | `payload.timestamp` or metadata |
| `country` | `payload.country` / features |
| `metadata` | `metadata` (+ derived `event_type` / `tenant_id` from gateway context) |

## Auth & idempotency

| Surface | Auth | Idempotency |
|---------|------|-------------|
| event-ingest `/v1/events` | API key | Header `Idempotency-Key` or `metadata.idempotency_key`; Redis cache when configured |
| decision-api `/v1/decisions/evaluate` | API key | Optional evaluate idempotency (env-gated) |
| orchestrator `/v1/ingest` | gateway / service auth | Entity UUID is the retry key for the same payment attempt |

## Contract violation errors (async ingest)

HTTP **422** with:

```json
{
  "error": "ingest_contract_violation",
  "reason_codes": ["ingest_event_type_invalid"],
  "message": "…"
}
```

Common reason codes: `ingest_tenant_id_empty`, `ingest_entity_id_empty`,
`ingest_event_type_empty`, `ingest_event_type_invalid`, `ingest_envelope_required`,
`ingest_idempotency_key_required`.

## Ownership

- **Public async ingest contract:** event-ingest (+ shared-core helpers)
- **Sync decision brain:** decision-api evaluate only
- **Orchestrator:** ingress + outbox side-effects; must not reimplement scoring

## Sync evaluate vs async enrichment (CQRS)

| Path | Owns | Must not |
|------|------|----------|
| **Sync** `POST /v1/decisions/evaluate` | Score + decision latency; may **read** Redis cache `fraud:async_osint:{tenant}:{entity}` | Wait on enrichment workers / OSINT HTTP |
| **Async** `fraud.enrichment.request` → integration-ingress | Refresh Redis blob (`updated_at`) | Block the evaluate response |

Lag budget: `ASYNC_ENRICH_MAX_AGE_MINUTES` (default 60). Stale cache → degrade tag `async_enrich:stale` + metric; features still merge (fail soft). See Phase 2 Wave A+B design under `docs/superpowers/specs/`.
