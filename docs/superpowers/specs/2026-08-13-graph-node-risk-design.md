# Persisted node risk — lookup, subgraph, top-N

**Date:** 2026-08-13  
**Status:** Approved (spec)  
**Related:** [graph-service](../../docs/services/graph-service.md), OpenAPI `contracts/openapi/graph-service.yaml`

## Goal

Calculate the existing entity-risk score for graph nodes, persist it, and query it two ways: every node in a lookup/subgraph payload, and a ranked list per tenant.

**Importance is not a second axis.** It is this same `risk_score` (0–100). No PageRank, GDS, or “priority = importance × risk” in this spec.

## Philosophy (unchanged)

- Decision-api / rules remain sole allow/deny. Stored graph scores are features, not decisions.
- AI / Shadow never write `risk_*` properties.
- Do not invent scores when Neo4j (or the active backend) is down.
- `0` is a real computed score (clean node). Unscored / absent storage is never stored as `0`.

## What already exists

- `compute_entity_risk` in `algorithms_neo4j.py` (and Janus/AGE twins): tags, flagged neighbors, community size, shared devices, connectivity; optional checkpoint multiplier.
- `GET /v1/analytics/entity-risk` — live Cypher; optional GNN-beta override when beta > base.
- Missing entity today: `risk_score: 0`, `risk_factors: ["entity_not_found"]`. **Keep that GET contract.**
- Orchestrator `degree_centrality` ingest signal — out of scope (not stored, not this API).
- Graph Explorer UI — out of scope this spec (API only).

## Architecture

graph-service owns compute and Neo4j properties. Orchestrator and decision-api keep calling live `GET /v1/analytics/entity-risk`; they do not SET scores.

```
upsert / tags / link
  → existing write
  → best-effort recompute+SET touched node ∪ 1-hop (cap 50)

GET /v1/analytics/entity-risk
  → live compute (+ optional gnn-beta)
  → SET that node only if found
  → return today’s body + scored=true (found) | scored=false (not found, score still 0)

GET /v1/subgraph | deep-context
  → read stored risk_* (null if never computed)

GET /v1/analytics/entity-risk/top
  → ORDER BY n.risk_score DESC WHERE risk_computed_at IS NOT NULL

POST /v1/analytics/entity-risk/refresh
  → one entity or tenant scan (cap), live compute+SET
```

## Stored properties

On a real node, after a successful compute:

| Property | Type | Meaning |
|----------|------|---------|
| `risk_score` | float 0–100 | Formula result (see persist source below) |
| `risk_factors` | string[] | Same list as `compute_entity_risk` |
| `risk_computed_at` | ISO-8601 UTC | When this SET ran |

Do not CREATE a node to store a score. Do not SET on `entity_not_found`.

Unscored node: these three properties absent.

## Sentinel vs live GET

| Surface | Missing entity | Node exists, never scored | Node scored 0 |
|---------|----------------|---------------------------|---------------|
| `GET /v1/analytics/entity-risk` | `risk_score: 0`, `risk_factors: ["entity_not_found"]`, `scored: false`, no SET | N/A (GET computes live) | `scored: true`, `risk_score: 0` |
| Subgraph / deep-context node | (node omitted) | `scored: false`, `risk_score: null`, `risk_computed_at: null` | `scored: true`, `risk_score: 0` |
| Top-N | excluded | excluded (`risk_computed_at` missing) | included if `min_score` allows |

`EntityRiskResponse` adds `scored: bool` (default false). Existing `risk_score` stays `ge=0` on this GET so old clients keep working.

## Persist source

- **GET entity-risk write-through:** persist the **returned** score after GNN-beta merge (what the client sees). Last writer wins, including `checkpoint=` (top-N has no checkpoint; it ranks whatever is stored).
- **Mutations and POST refresh:** persist `compute_entity_risk` only (no GNN HTTP per link). Beta catch-up is the next live GET or an explicit refresh after GET.

Shared helper: `persist_entity_risk(tenant_id, entity_id, payload) -> None`. SET only if the payload is a found compute (`"entity_not_found"` not in factors). Swallow SET errors; never fail the parent HTTP.

## Write path

After a successful entity upsert, tag update, or link create: recompute+persist the touched node(s) and undirected 1-hop neighbors (same `tenant_id`).

- Link: union of both endpoints and each of their 1-hops.
- Cap **50** nodes per mutation (touched endpoints first, then neighbors). ponytail: hub edges otherwise fan out; upgrade = queue.
- Best-effort: log failures; parent write still 200.

Community size for nodes beyond 1 hop stays stale until refresh or a live GET write-through.

## Query APIs

### `POST /v1/analytics/entity-risk/refresh`

Auth: same as other graph-service analytics (`API_KEYS`).

Body: `{ "tenant_id": str, "entity_id"?: str, "limit"?: int }`

- With `entity_id`: live compute+SET that entity. **404** if missing. Return `{ "updated": 1, "skipped": 0, "truncated": false }`.
- Tenant only: scan nodes `ORDER BY external_id`, compute+SET each. `limit` default **5000**, clamp **1–20000**. Return `{ "updated", "skipped", "truncated" }`. `truncated=true` when more nodes exist than `limit`. No cursor in v1 (re-call; upgrade = `after_external_id`).

### `GET /v1/analytics/entity-risk/top`

Query: `tenant_id` (required), `limit` default 50 clamp 1–200, `min_score` default 0.

Response: `{ "entities": [ { "entity_id", "labels", "risk_score", "risk_factors", "risk_computed_at" } ] }`  
`WHERE n.risk_computed_at IS NOT NULL AND n.risk_score >= min_score`  
`ORDER BY n.risk_score DESC, n.external_id ASC`.

### Subgraph and deep-context

Each node object gains `scored`, `risk_score` (`number | null`), `risk_computed_at` (`string | null`) from stored properties. Do not run `compute_entity_risk` per node on these reads.

## Errors

- Missing required query/body fields: existing 422.
- Refresh unknown `entity_id`: 404, no SET.
- Graph backend down: same 502/empty as today’s subgraph/analytics; do not invent scores.
- GET write-through SET failure: still return live body; log; do not 500.
- Mutation SET failure: swallow.

## Backends

Same three persist fields on Neo4j, Janus, and AGE if that backend already implements `compute_entity_risk`. No GDS plugin.

## Tests

Pytest; mock driver where existing algorithm tests already do.

1. Found compute SET `risk_score` / `risk_factors` / `risk_computed_at`; `entity_not_found` does not SET; GET still `0` + `entity_not_found` + `scored: false`.
2. GET write-through: stored properties match the HTTP body (post-beta when beta applied).
3. Link/tag write triggers recompute for both ends and a 1-hop neighbor; cap 50.
4. Subgraph node without `risk_computed_at` → `scored: false`, `risk_score: null` (not `0`).
5. Top-N excludes unscored; orders by stored score; `min_score`; limit clamp.
6. Refresh entity 404; tenant refresh respects cap and `truncated`.

## Out of scope

- Graph Explorer / SPA ranking UI
- New centrality / importance metric
- Decision-api evaluate reading stored properties (keeps live GET)
- Cursor pagination for tenant refresh
- Changing `entity_not_found` GET `risk_score` away from `0`
