# Hunt depth v1

Day-1 AGE Hunt is **depth-1**. `GET /v1/subgraph` and AGE `query_subgraph` walk one hop from the seed (`MATCH (root)-[e]-(nb)`). Community size on the AGE path is 1-hop degree + 1. Desk `depth` (1–5) and a `depth` query default are request hints — they are not a multi-hop GA.

Empty `GRAPH_SERVICE_URL` = Hunt and hops **off** (same plane-off as [graph-planes-v1](graph-planes-v1.md)). No invented neighbors.

## Schema (`tarka.hunt_depth/v1`)

Honesty fields for Hunt / subgraph responses. API emit is this slice (D7.3): every on-plane `GET /v1/subgraph` body includes these fields. Empty `GRAPH_SERVICE_URL` stays plane-off (decision-api hop / desk), not a graph-service response.

| Field | Type | Honesty |
|-------|------|---------|
| `schema_id` | string | `tarka.hunt_depth/v1` |
| `hunt_depth_max` | int | Day-1 AGE Hunt: **1**. Raise only when a later slice documents an AGE-safe fixed bound and tests it. |
| `depth_requested` | int | Caller `depth` (desk may send 1–5). |
| `depth_applied` | int | Hops actually walked. Day-1 AGE, plane on: **1**. |
| `degrade_reason` | string \| null | Set when `depth_requested` > `depth_applied`. Day-1 token: `hunt:depth_capped`. Null when requested ≤ applied. |

Empty URL: plane-off / `graph:missing`. Do not emit a hop list. Do not invent `depth_applied` > 0.

## Multi-hop (later)

If a later slice ships AGE-safe **fixed** k-hop (`k <= hunt_depth_max`), `depth_applied` reports k. `degrade_reason` fires when requested > max. That is still not variable-length path product language and not an identity SKU.

## Degrade (D7.2–D7.3)

Desk glass and Hunt API must show `depth_requested` vs `depth_applied` plus `degrade_reason`. Never silent truncate that reads as a full multi-hop success.

## Out of scope

Variable-length path Hunt product. Identity SKU / entity-resolution product. GNN live. Invented neighbors when the URL is empty.
