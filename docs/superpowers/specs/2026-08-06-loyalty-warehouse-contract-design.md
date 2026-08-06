# Loyalty warehouse HTTP contract (Track C)

Date: 2026-08-06  
Status: approved (Critical A–E plan)

## Goal

Fetch tenant loyalty hygiene feeds + program config from an HTTP warehouse URL, validate, and materialize evaluate-ready `loyalty_feed_snapshot` / `loyalty_program_config`. Fail-closed on incomplete/stale.

## Response shape (warehouse)

```json
{
  "schema_id": "tarka.loyalty_warehouse_pack/v1",
  "entity_id": "e1",
  "as_of": "2026-08-06T12:00:00Z",
  "loyalty_feed_snapshot": { "...": "same as metadata.loyalty_feed_snapshot" },
  "loyalty_program_config": { "...": "same as metadata.loyalty_program_config" }
}
```

## Client

- `decision_api.loyalty_warehouse.fetch_loyalty_warehouse_pack(url, *, timeout=10)` via httpx
- `scripts/oss/loyalty_warehouse_fetch.py` CLI → JSON stdout / file
- CI smoke with stdlib mock HTTP (complete + incomplete)

## Non-goals

- BigQuery/Snowflake drivers  
- Claiming named-tenant production warehouse effectiveness
