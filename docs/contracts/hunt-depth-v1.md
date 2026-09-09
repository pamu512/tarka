# Hunt depth v1

## Path B (D7.4)

**Path B — enforced depth-1.** `hunt_depth_max=1`. AGE 1.6 finding: Hunt `query_subgraph` is `MATCH (root)-[e]-(nb)`. No `age_unnest`. `entity_risk_sql` community_size is 1-hop degree + 1. A `[*1..{depth}]` string in another AGE helper is not the Hunt product. Path A (AGE-safe fixed k-hop) was not proven; do not raise `hunt_depth_max`.

`GET /v1/subgraph` and AGE `query_subgraph` walk one hop from the seed. Desk `depth` (1–5) and a `depth` query default are request hints. `depth_requested` > 1 → `depth_applied=1` and `degrade_reason=hunt:depth_capped`. Walk stays 1.

Empty `GRAPH_SERVICE_URL` = Hunt and hops **off** (same plane-off as [graph-planes-v1](graph-planes-v1.md)). No invented neighbors.

Operator day-1: [graph-analysis — Day-1 Hunt depth](../docs/guides/graph-analysis.md#day-1-hunt-depth). Next-agent regression: [hunt-depth-regression](../testing/hunt-depth-regression.md).

## Schema (`tarka.hunt_depth/v1`)

Honesty fields for Hunt / subgraph responses. API emit is this slice (D7.3): every on-plane `GET /v1/subgraph` body includes these fields. Empty `GRAPH_SERVICE_URL` stays plane-off (decision-api hop / desk), not a graph-service response.

| Field | Type | Honesty |
|-------|------|---------|
| `schema_id` | string | `tarka.hunt_depth/v1` |
| `hunt_depth_max` | int | Path B AGE Hunt: **1**. Raise only when a later slice documents an AGE-safe fixed bound and tests it. |
| `depth_requested` | int | Caller `depth` (desk may send 1–5). |
| `depth_applied` | int | Hops actually walked. Path B, plane on: **1**. |
| `degrade_reason` | string \| null | Set when `depth_requested` > `depth_applied`. Path B token: `hunt:depth_capped`. Null when requested ≤ applied. |

Empty URL: plane-off / `graph:missing`. Do not emit a hop list. Do not invent `depth_applied` > 0.

## Not Path A

AGE-safe fixed k-hop was not proven on AGE 1.6. Do not raise `hunt_depth_max`. A later slice may ship a tested fixed bound; until then Path B holds.

## Degrade (D7.2–D7.4)

Desk glass and Hunt API must show `depth_requested` vs `depth_applied` plus `degrade_reason`. Prefer live API fields. Never silent truncate that reads as a full multi-hop success.

## Out of scope

Non-claims — do not read Path B as any of these:

- Unlimited Hunt
- Variable-length path product
- Identity SKU / entity-resolution product
- GNN live
- Invented neighbors when `GRAPH_SERVICE_URL` is empty
- Path A without a tested AGE 1.6 bound
- Python BFS that claims AGE multi-hop
