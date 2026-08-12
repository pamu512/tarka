# Velocity counter keys for rule authors (v1.2.0)

Use these **normalized** names in rule packs and evaluate payloads. They match `AggregateStore.compute_features`, [`counter_manifest_v1.json`](../../../../services/decision-api/src/decision_api/data/counter_manifest_v1.json), and `GET /v1/internal/counters/manifest`. Do not invent alternate spellings.

## Multi-window event counts (Day 60 contract)

Always available when events are recorded for the entity:

| Key | Window | Rule example |
|-----|--------|----------------|
| `event_count_5m` | 5 minutes | `"event_count_5m": { "$gt": 10 }` |
| `event_count_1h` | 1 hour | `"event_count_1h": { "$gte": 25 }` |
| `event_count_24h` | 24 hours | `"event_count_24h": { "$gte": 100 }` |

**Feature-service:** With shared Redis (`FEATURE_SERVICE_REDIS_URL` / `REDIS_URL`) and the same `AGG_KEY_VERSION` as decision-api, `POST /v1/velocity/query` returns these under `velocity_counters` with the **same values** as evaluate features for the same tenant/entity after the same events.

## Distinct counters (require payload fields)

| Key | Requires in payload | Notes |
|-----|---------------------|--------|
| `distinct_device_id_24h` | `device_id` | 24h distinct device IDs |
| `distinct_ip_address_24h` | `ip_address` | 24h distinct IPs |
| `distinct_session_id_24h` | `session_id` | 24h distinct sessions — **omit key from rules** if you do not send `session_id` |

Example evaluate payload fragment:

```json
{
  "tenant_id": "demo",
  "entity_id": "user-123",
  "payload": {
    "amount": 49.99,
    "session_id": "sess-abc",
    "device_id": "dev-xyz",
    "event_count_5m": 8,
    "event_count_1h": 40,
    "event_count_24h": 200
  }
}
```

After live traffic, prefer **feature-service** or evaluate-returned features over hand-set counts in payloads.

## Redis key versioning

Set **`AGG_KEY_VERSION`** identically on decision-api writers, replay scripts, and feature-service readers. Keys become `fraud:agg:{version}:{tenant}:{entity}:{metric}`. See [redis-agg-key-version-migration.md](../redis-agg-key-version-migration.md).

## Related

- [counter-replay-parity.md](../counter-replay-parity.md) — Epic C RC gates
- [api-bot-credential-defense.md](./api-bot-credential-defense.md) — velocity in rules
- [quickstart.md](../../quickstart.md) — quick evaluate curl
