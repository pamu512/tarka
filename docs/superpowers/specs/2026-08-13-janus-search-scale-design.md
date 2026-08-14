# Janus search scale (ladder rungs 3–5)

**Date:** 2026-08-13  
**Status:** Approved  
**Related:** [property search](./2026-08-13-graph-property-search-design.md), [vertex identity + composite (parked)](./2026-08-13-janus-vertex-identity-index-design.md), [janusgraph-adapter](../../../services/graph-service/docs/janusgraph-adapter.md)

Ladder rungs **3, 4, and 5**. Rungs 1–2 stay parked: ingest vertices without `tenant_id` / `external_id` still will not appear in search or seed subgraph.

## Goal

Janus typeahead and neighborhood load stop doing **one Gremlin round-trip per vertex**. Search uses a Lucene mixed index with **prefix** match. Owner hop and fallback scans are capped. Subgraph walks **one round-trip per depth layer**.

## Philosophy (unchanged)

- Decision-api / rules remain sole allow/deny.
- Do not invent graph, nodes, ids, or scores.
- Unscored stays `scored: false`, `risk_score: null`.
- Empty `q` → `{ "entities": [] }` 200, no scan (HTTP handler unchanged).

## What already exists

- Janus search: `g.V().has("tenant_id").toList()` then `elementMap()` per vertex; `both()` unbounded; no search cap.
- Subgraph / deep-context: Python BFS, `bothE` + `elementMap` per vertex.
- Analytics cap `JANUSGRAPH_ANALYTICS_VERTEX_CAP` (default 8000) does not apply to search.
- Demo `index.search.backend = lucene`. No mixed index is created in code.
- Property search contract: allowlisted string fields, 1-hop Person/Account/User, `matched_on` / `via`, label after resolve.

## Match (Janus only)

Case-insensitive **prefix** on `SEARCH_PROP_KEYS` (same allowlist as property search). Python re-check: `isinstance(str) and val.casefold().startswith(needle.casefold())`. Lucene hits that fail the re-check are dropped (tokenization must not invent matches).

Neo4j and AGE stay case-insensitive **CONTAINS**. Document the Janus difference.

## Mixed index (rung 3)

On first Janus connect (`GRAPH_BACKEND=janusgraph`):

- Gremlin Client.submit Groovy: get-or-create property keys; mixed index **`vertexSearch`** on backend **`search`**.
- Keys: `tenant_id` with STRING mapping; each `SEARCH_PROP_KEYS` entry with TEXTSTRING mapping.
- Idempotent if `vertexSearch` exists. REGISTERED/INSTALLED: do not block HTTP; use fallback scan.
- Mgmt failure: log, serve via fallback scan.

**Indexed search:** for each allowlisted field, run  
`g.V().has("tenant_id", tenant).has(field, textContainsPrefix(q)).limit(50)`  
Union vertex ids, then **one** `valueMap(true)` (or equivalent batch hydrate) for the union. No tenant-wide `elementMap` loop.

## Hydrate and owner hop (rung 4)

- Search hits: batch `valueMap`, not per-tenant-vertex `elementMap`.
- Owner hop: `g.V(v).both().limit(10)` then batch hydrate. `cap_identifier_owners` **dedupes `(via_id, owner_entity_id)` before counting** so duplicate edges do not consume fan-out slots.
- **Subgraph and deep-context:** replace the per-vertex `bothE` / `elementMap` loop with **one Gremlin round-trip per depth layer** (`bothE` + otherV + `valueMap` for the frontier). Frontend prune 3000 unchanged. No silent per-vertex edge cap (super-node RAM is a known ceiling; follow-on).

## Cap and `truncated` (rung 5)

When `vertexSearch` is not ENABLED:  
`g.V().has("tenant_id", tenant).limit(JANUSGRAPH_ANALYTICS_VERTEX_CAP)` then prefix-filter in Python. If the cap was hit, response `truncated: true`.

Indexed path: `truncated: false` unless a layer/tooling signal says otherwise (default false).

**HTTP:** `GET /v1/entities/search` body:

```
{ "entities": [ ...existing hit shape... ], "truncated": false }
```

`truncated` required in OpenAPI, default false. Neo4j/AGE always `false`. Frontend may ignore it this spec (optional small banner later — not required). Mocks include `truncated: false`.

## Errors

- Empty `q`: unchanged `[]`, no store, `truncated` omitted or false.
- Graph plane down: existing failover, no invented hits.
- Index missing: capped scan + `truncated`, not 5xx.
- Do not invent hits, `via`, or scores.

## Tests

1. Janus search source: `textContainsPrefix`, `vertexSearch`, batch `valueMap` (or project), `both().limit(10)`, no `for v in g.V().has("tenant_id"` + `elementMap` tenant loop.
2. Fallback branch: `limit(` + analytics cap name/value; sets `truncated`.
3. `cap_identifier_owners`: 12 duplicate edges to 10 owners → 10 owners.
4. Prefix re-check: Lucene-style extra token that does not `startswith` is dropped.
5. Subgraph source: no per-vertex `bothE().toList()` in a Python `for v in frontier` loop; depth-layer traversal present.
6. OpenAPI + mock + Neo4j HTTP still `{entities}` with `truncated` false; empty `q` still no store call.
7. Neo4j/AGE search source still `CONTAINS`, not `textContainsPrefix`.
8. Docs: `janusgraph-adapter.md` + graph-service search section — Janus prefix, `truncated`, ingest-without-identity still misses.

## Out of scope

- Rungs 1–2 (ingest `tenant_id`/`external_id` stamp, `byTenantExternal` composite)
- Elasticsearch; changing Lucene off the demo
- Prefix on Neo4j/AGE
- Inventing `entity_id` / tenant
- Per-vertex subgraph edge cap
- Search UI banner (optional later)
- `search_keys[]` on write
