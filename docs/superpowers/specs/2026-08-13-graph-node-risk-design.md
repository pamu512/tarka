# Persisted node risk — lookup, subgraph, top-N

**Date:** 2026-08-13  
**Status:** Amended (pending re-review)  
**Related:** [graph-service](../../docs/services/graph-service.md), [AgentRun spine](./2026-08-13-agent-run-spine-design.md), OpenAPI `contracts/openapi/graph-service.yaml`

## Goal

Calculate a per-node **risk** score, persist it, and query it: point lookup, every node in a subgraph (depth **1–5**), and a ranked list per tenant. Investigation-agent (and AgentRun graph context) must see the same scores and growth flags — no second “importance” axis, no PageRank/GDS.

**Importance is this same `risk_score`.** Fast-growing relation counts and larger-than-peer degree raise that score and add `risk_factors` the model can cite.

## Philosophy (unchanged)

- Decision-api / rules remain sole allow/deny. Stored graph scores are features, not decisions.
- AI / Shadow never write `risk_*` properties.
- Do not invent scores when the graph backend is down.
- `0` is a real computed score (clean node). Unscored storage is never `0`.
- Do not invent edge timestamps. Edges without `observed_at` / `created_at` / `updated_at` count toward **degree** only, not **growth**.

## What already exists

- `compute_entity_risk`: tags, flagged neighbors, community size, shared devices, connectivity (≥5 / ≥10); checkpoint hop clamp 1–5 (community default 3).
- `GET /v1/analytics/entity-risk` — live Cypher; optional GNN-beta if beta > base.
- Missing entity GET: `risk_score: 0`, `risk_factors: ["entity_not_found"]`. **Keep that contract.**
- `GET /v1/subgraph?depth=` already clamps **1–5** (HTTP default **2**). Investigation tools `subgraph` / `subgraph_with_velocity` use the same clamp; default depth **2**.
- `subgraph_with_velocity` overlays decision-api **transaction** velocity (`/v1/analyst/entity-velocity`). That is **not** graph edge growth. This spec adds graph relation growth on the node; do not replace the transaction overlay.
- Orchestrator `degree_centrality` ingest signal — still not a stored node property.
- Graph Explorer UI — out of scope.

## Architecture

graph-service owns compute and node properties. Orchestrator and decision-api keep calling live `GET /v1/analytics/entity-risk`; they do not SET scores.

```
upsert / tags / link
  → existing write
  → SET link observed_at=now if missing
  → best-effort recompute+SET touched ∪ 1-hop (cap 50)

GET /v1/analytics/entity-risk
  → live compute (+ optional gnn-beta)
  → SET that node only if found
  → return body + scored + growth counters

GET /v1/subgraph?depth=1..5 | deep-context
  → read stored risk_* / growth (null if never computed)

GET /v1/analytics/entity-risk/top
  → ORDER BY n.risk_score DESC WHERE risk_computed_at IS NOT NULL

POST /v1/analytics/entity-risk/refresh
  → one entity or tenant scan (cap), live compute+SET
  → tenant scan also refreshes GraphRiskStats peer p90 by label

investigation-agent subgraph / subgraph_with_velocity
  → same subgraph JSON (risk + growth on nodes), depth clamp 1–5
```

## Formula additions (still 0–100, `min(round(score * checkpoint_mult), 100)`)

Keep existing tag / flagged-neighbor / community / shared-device points.

**Degree (replace absolute connectivity when peer stats exist):**

| Condition | Points | `risk_factors` |
|-----------|--------|----------------|
| `GraphRiskStats` present and `relation_count >= max(10, peer_p90)` for the node’s primary label | +15 | `high_degree_vs_peers:{count}:p90={p90}` |
| Else `relation_count >= 10` | +10 | `high_connectivity:{count}` (unchanged) |
| Else `relation_count >= 5` | +5 | `moderate_connectivity:{count}` (unchanged) |

Do not stack peer points with absolute connectivity on the same node.

**Relation growth** (undirected incident edges; Device and Account/User use the same counters — neighbor type does not matter):

`relation_growth_1h` / `relation_growth_24h` = count of incident relationships whose `coalesce(observed_at, created_at, updated_at)` is inside that window (UTC). Untimestamped edges: excluded from growth, included in `relation_count`.

| Condition | Points | `risk_factors` |
|-----------|--------|----------------|
| `relation_growth_1h >= 5` | +20 | `fast_growth_1h:{n}` |
| `relation_growth_24h >= 15` | +15 | `fast_growth_24h:{n}` |

Both growth flags may apply. `create_link`: if the payload has no `observed_at`, SET `observed_at` to now (UTC) so future growth is measurable. Do not backfill old edges.

## Stored properties

On a real node, after a successful compute:

| Property | Type | Meaning |
|----------|------|---------|
| `risk_score` | float 0–100 | Formula result (see persist source) |
| `risk_factors` | string[] | Including `fast_growth_*` / `high_degree_vs_peers` when they fired |
| `risk_computed_at` | ISO-8601 UTC | When this SET ran |
| `relation_count` | int | Undirected degree |
| `relation_growth_1h` | int | Timestamped new incident edges in 1h |
| `relation_growth_24h` | int | Timestamped new incident edges in 24h |

Do not CREATE a node to store a score. Do not SET on `entity_not_found`. Unscored node: these properties absent.

**Peer stats** (tenant refresh only): one `(:GraphRiskStats {tenant_id})` node with `p90_degree_by_label` (JSON map label → p90 of `relation_count` on scanned nodes) and `stats_computed_at`. If the tenant scan is `truncated`, p90 is from the scanned set only (documented in the refresh response). Live GET reads this node; if missing, use absolute connectivity fallback.

## Sentinel vs live GET

| Surface | Missing entity | Node exists, never scored | Node scored 0 |
|---------|----------------|---------------------------|---------------|
| `GET /v1/analytics/entity-risk` | `risk_score: 0`, `risk_factors: ["entity_not_found"]`, `scored: false`, no SET | N/A (GET computes live) | `scored: true`, `risk_score: 0` |
| Subgraph / deep-context node | (node omitted) | `scored: false`, `risk_score: null`, growth fields `null` | `scored: true`, `risk_score: 0` |
| Top-N | excluded | excluded | included if `min_score` allows |

`EntityRiskResponse` adds `scored: bool` (default false), `relation_count`, `relation_growth_1h`, `relation_growth_24h` (0 on not-found). Existing `risk_score` stays `ge=0` on this GET.

## Persist source

- **GET entity-risk write-through:** persist the **returned** score after GNN-beta merge. Last writer wins, including `checkpoint=`. Growth counters always come from `compute_entity_risk` (beta does not invent them).
- **Mutations and POST refresh:** persist `compute_entity_risk` only (no GNN HTTP per link).

Shared helper: `persist_entity_risk(tenant_id, entity_id, payload) -> None`. SET only if found (`"entity_not_found"` not in factors). Swallow SET errors; never fail the parent HTTP.

## Write path

After a successful entity upsert, tag update, or link create: recompute+persist the touched node(s) and undirected **1-hop** neighbors (same `tenant_id`).

- Link: union of both endpoints and each of their 1-hops.
- Cap **50** nodes per mutation (touched endpoints first). ponytail: hub edges otherwise fan out; upgrade = queue.
- Best-effort: log failures; parent write still 200.
- **Do not** recompute a 5-hop neighborhood on writes. Depth 5 is a **query** bound.

Community size and peer p90 for nodes beyond 1 hop stay stale until refresh or a live GET write-through.

## Query APIs

### `POST /v1/analytics/entity-risk/refresh`

Auth: same as other graph-service analytics (`API_KEYS`).

Body: `{ "tenant_id": str, "entity_id"?: str, "limit"?: int }`

- With `entity_id`: live compute+SET that entity. **404** if missing. Return `{ "updated": 1, "skipped": 0, "truncated": false }`. Does not rewrite tenant p90.
- Tenant only: scan nodes `ORDER BY external_id`, compute+SET each, then rewrite `GraphRiskStats` p90 from **those** nodes’ `relation_count` grouped by primary label. `limit` default **5000**, clamp **1–20000**. Return `{ "updated", "skipped", "truncated" }`. No cursor in v1.

### `GET /v1/analytics/entity-risk/top`

Query: `tenant_id` (required), `limit` default 50 clamp 1–200, `min_score` default 0.

Response entities include `risk_score`, `risk_factors`, `risk_computed_at`, `relation_count`, `relation_growth_1h`, `relation_growth_24h`.  
`WHERE n.risk_computed_at IS NOT NULL AND n.risk_score >= min_score`  
`ORDER BY n.risk_score DESC, n.external_id ASC`.

### Subgraph and deep-context (≤5 hops)

`GET /v1/subgraph?entity_id=&tenant_id=&depth=` — `depth` clamp **1–5**, HTTP default **2**. Each node includes `scored`, `risk_score` (`number | null`), `risk_computed_at`, `relation_count`, `relation_growth_1h`, `relation_growth_24h` from stored properties. Do not run `compute_entity_risk` per node on these reads.

## AI (investigation-agent)

No new tool. `subgraph` and `subgraph_with_velocity` already call `/v1/subgraph` with `_validate_depth` **1–5**. They return the new node fields as-is. Transaction velocity overlay stays. Default tool depth stays **2**; the model may pass `depth` up to **5**.

Playbook/persona: one added line — when checking rings, shared devices, or mule fan-out, call `subgraph_with_velocity` with depth up to 5 and cite `risk_factors` (`fast_growth_1h`, `fast_growth_24h`, `high_degree_vs_peers`). Do not claim growth if those factors are absent.

AgentRun: if `graph_neighborhood` vertices already carry these fields, persist them on the run. Chat must not fetch a 5-hop subgraph on every turn. `graph_missing` policy from the AgentRun spine spec is unchanged. Shadow does not write graph scores and does not auto-resolve.

## Errors

- Missing required query/body fields: existing 422.
- Refresh unknown `entity_id`: 404, no SET.
- `depth` / `limit` out of range: clamp (same as today), do not 400.
- Graph backend down: same 502/empty as today’s subgraph/analytics; do not invent scores or timestamps.
- GET write-through SET failure: still return live body; log; do not 500.
- Mutation SET failure: swallow.

## Backends

Same persist fields on Neo4j, Janus, and AGE if that backend already implements `compute_entity_risk`. Growth counts use the same timestamp coalesce. No GDS plugin.

## Tests

Pytest; mock driver where existing algorithm tests already do.

1. Found compute SET score/factors/computed_at/growth counters; `entity_not_found` does not SET; GET still `0` + `entity_not_found` + `scored: false`.
2. GET write-through: stored properties match the HTTP body (post-beta score; growth from compute).
3. Link/tag write triggers recompute for both ends and a 1-hop neighbor; cap 50. New link without `observed_at` stores now.
4. Subgraph node without `risk_computed_at` → `scored: false`, `risk_score: null` (not `0`).
5. Top-N excludes unscored; orders by stored score; `min_score`; limit clamp.
6. Refresh entity 404; tenant refresh respects cap and `truncated`; tenant refresh writes `GraphRiskStats` p90.
7. Five timestamped edges in 1h → `fast_growth_1h` and score ≥ 20 before other factors; untimestamped edges do not increment growth.
8. Degree ≥ max(10, p90) with stats present → `high_degree_vs_peers`, not stacked with `high_connectivity`.
9. Subgraph `depth=5` accepted; investigation-agent `_validate_depth(5)==5` and tool result includes node `risk_score` when stored. `depth=6` clamps to 5.

## Out of scope

- Graph Explorer / SPA ranking UI
- PageRank / betweenness / a second importance score
- Decision-api evaluate reading stored properties (keeps live GET)
- Replacing `subgraph_with_velocity` transaction overlay
- Cursor pagination for tenant refresh
- Changing `entity_not_found` GET `risk_score` away from `0`
- 5-hop recompute on every graph write
- Fetching 5-hop subgraph on every chat turn
