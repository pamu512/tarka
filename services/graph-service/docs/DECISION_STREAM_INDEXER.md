# Decision stream → graph edge indexer

## Goal

Consume NATS JetStream subject `fraud.decisions.>` (same stream as `analytics-sink`) and project
`(tenant_id, entity_id, device_id, ip, …)` edges into the graph backend (JanusGraph / Neo4j / AGE)
for **real-time** Visual Link Analysis.

## Non-goals

- This repository path does **not** ship a long-running NATS consumer in `graph-service` yet
  (operational isolation: graph writers should not starve interactive Gremlin/HTTP workers).

## Recommended deployment

1. Run a dedicated sidecar or `services/graph-edge-indexer` worker (future crate) with:
   - Pull consumer on `fraud.decisions.>` durable `tarka-graph-indexer`
   - Idempotent upsert into graph store using `trace_id` as correlation id
2. Cap fan-out: batch 500 edges / 250 ms; on failure `NAK` with delay (mirror `analytics-sink` policy).
3. Detect **super-nodes** (degree > 1000) at index time: store aggregated `HAS_IP` weight instead of materializing every edge.

## Security

- Scrub PII fields using the same tokenization policy as `event-ingest` before persisting graph properties.
