# Graph investigation workspace (Palantir-style)

**Date:** 2026-08-13  
**Status:** Draft  
**Related:** [persisted node risk](./2026-08-13-graph-node-risk-design.md), [graph-service](../../docs/services/graph-service.md), OpenAPI `contracts/openapi/graph-service.yaml`

## Goal

One investigation surface at `/graph`: **search an object, know its type, work the neighborhood**. Merge Graph Explorer and Link Analysis into a Palantir-style workspace (search + type facets on top, histogram/filters left, force-graph canvas, dossier always on the right). Ontology in this spec is **types as facets and filters**, not a schema editor.

## Philosophy (unchanged)

- Decision-api / rules remain sole allow/deny. Stored `risk_score` is a feature, not a decision.
- Do not invent graph, nodes, paths, or scores when the graph plane is down.
- `0` is a computed clean score. Unscored nodes stay `scored: false`, `risk_score: null` — never treat null as 0 in filters or paint.
- AI / Shadow do not gain a new tool this spec. They already see stored risk on `subgraph`.

## What already exists

- `/graph` — Graph Explorer (vis-network, entity-id form, Analyze → communities / rings, `GraphContextPanel`).
- `/graph/link-analysis` — force-graph, depth 1–5, prune cap **3000**, risk overlay, dossier slide-over.
- `GET /v1/subgraph`, `deep-context`, `path-explain`, `communities`, `fraud-rings`, `schema/{tenant_id}`, `entity-risk/top`.
- Subgraph nodes already carry `scored`, `risk_score`, `risk_factors`, `relation_count`, `relation_growth_1h`, `relation_growth_24h`.
- Omni-search (`/v1/omni-search`) finds **case-table** entity ids, not graph nodes. Do not use it as the workspace typeahead.
- `/graph/mule-path` stays a sibling. Case/workbench links already target `/graph?entity_id=&tenant_id=`.

## Architecture

```
GET /v1/schema/{tenant}          → type chips (read-only)
GET /v1/entities/search          → typeahead (NEW)
GET /v1/analytics/entity-risk/top → empty-state list
GET /v1/subgraph depth=1..5      → seed canvas (default 2)
GET /v1/subgraph depth=1         → expand: merge into canvas
GET /v1/analytics/path-explain   → path overlay seed → selected
GET /v1/entities/{id}/deep-context → dossier
GET communities / fraud-rings    → highlight members already on canvas
client histogram/filters         → hide nodes; no extra graph query
```

**Routes**

- `/graph` is the workspace. Query: `entity_id`, `tenant_id`, `depth` (clamp 1–5, default 2). Also accept aliases `entity` and `tenant` so older links keep working; write-back URL uses `entity_id` / `tenant_id` only.
- `/graph/link-analysis` **redirects** to `/graph` preserving those params.
- Nav: one item labeled **Graph** (drop “Link analysis (2D)”). Command palette + `accessModuleCatalog` match.
- vis-network Explorer page goes away. Canvas engine is `LinkAnalysisForceGraph`.

**Layout (locked)**

| Region | Contents |
|--------|----------|
| Top | Typeahead + **search** type chips (schema, set the search `label` param only) + tenant + seed depth 1–5 |
| Left | Histogram of **loaded** nodes; min risk; growth; rings/communities |
| Center | Force-graph; failover banner when the graph plane is disabled |
| Right | Dossier always open (`GraphContextPanel` in-column, not a slide-over) |

## New API: `GET /v1/entities/search`

Auth: same `API_KEYS` as other graph-service reads.

Query:

| Param | Required | Rules |
|-------|----------|--------|
| `tenant_id` | yes | exact tenant match |
| `q` | no | strip; max 256. Empty or missing → `{ "entities": [] }` (200), no scan |
| `label` | no | keep nodes where this string is in `labels`. Unknown label → empty list, not 400 |
| `limit` | no | default 20, clamp 1–50 |

Match: case-insensitive **contains** on `external_id` / node id only (parameterized; no property-bag search).  
Order: `risk_score DESC NULLS LAST`, then `external_id ASC`.  
Response:

```
{ "entities": [{ "entity_id", "tenant_id", "labels": [str], "scored": bool, "risk_score": number | null }] }
```

`scored` / `risk_score` from stored properties (same sentinel as subgraph). Do not live-compute risk on search.

Implement on every backend that already implements `query_subgraph` (Neo4j, Janus, AGE). OpenAPI in `contracts/openapi/graph-service.yaml`. Frontend `graph.searchEntities` + mock.

## Canvas load and expand

**Seed load** (search pick, empty-state top-N click, or URL with `entity_id`): `GET /v1/subgraph` at URL `depth`, prune to `LINK_ANALYSIS_MAX_NODES` (3000) with the existing worker, replace canvas. Seed is the dossier selection.

**Expand** (dossier “Expand” or double-click node): `GET /v1/subgraph` for **that** id at **depth 1**, union nodes by id and edges by `(from_id, to_id, type)`, then prune toward the **seed** (not the expanded node) if over cap. Do not refetch the whole seed neighborhood. URL `depth` does not change. Keep last canvas if the expand call fails.

**Changing seed depth** in the top bar: replace canvas (new seed load). Not an expand.

**Path:** dossier “Path from seed” while a non-seed node is selected → `GET /v1/analytics/path-explain?tenant_id=&from_entity_id={seed}&to_entity_id={selected}&depth=3`. Highlight returned nodes/edges. No path or error: dossier message; canvas graph data unchanged.

**Paint:** `displayRisk` is the subgraph node’s stored `risk_score` (`null` if unscored). Do not call live `GET /v1/analytics/entity-risk` or `risk-propagation` on seed load (Link Analysis does that today; this workspace does not).

## Filters (client-side)

Histogram counts and ring lists always use the **unfiltered loaded** set.

- **Type:** primary label = `labels[0]` or `"Custom"`. Histogram shows types **present on the loaded canvas** (not the full schema). Clicking a type **hides** other types (and their edges). “All types” clears. Search-bar chips are separate (schema → search `label` only; they never hide canvas nodes).
- **Min risk:** hide scored nodes with `risk_score < min`. Unscored nodes stay visible unless **Scored only** is on (default **off**).
- **Growth:** when on, keep nodes with `relation_growth_1h >= 5` **or** `relation_growth_24h >= 15`. Unscored / null growth hidden while this toggle is on.
- **Rings / communities:** same fetch as Explorer Analyze (on demand, tenant-wide). Click a ring/community → highlight member ids **already on the canvas**. Do not auto-load missing members.

Paint: existing risk fill on `displayRisk`. Hidden ≠ deleted.

## Empty state and search UX

No `entity_id` in URL: show `GET /v1/analytics/entity-risk/top` (`limit=20`) for the tenant. Click a row → set URL and seed-load. Empty top-N or empty typeahead: empty list, not an error toast.

Typeahead: debounce 200ms; ignore stale responses. Type chip on the search bar sets `label` on search; it does not filter the canvas (histogram does).

Tenant default: `localStorage tarka.tenant_id`, else `demo` (same as Link Analysis).

## Errors

- Graph plane disabled: existing Explorer banner; no search / subgraph / analytics calls.
- Search backend 5xx: search dropdown error string; canvas untouched.
- Seed subgraph fail: error banner; no fake nodes.
- Expand fail: banner; keep last canvas.
- Over cap: existing prune note.
- Missing seed: subgraph empty state (no invented neighborhood). `GET entity-risk` `entity_not_found` contract unchanged.
- Path miss: dossier text only.

## Tests

1. Search: contains match; `label` filter; other tenant omitted; `q` empty → `[]`; `limit` clamp; `risk_score` null when unscored.
2. Frontend filter: type hide; unscored node remains at min-risk unless scored-only; growth toggle uses counters not “null as 0”.
3. Expand merge keeps seed; union does not duplicate edges; prune still caps at 3000.
4. `/graph/link-analysis?entity_id=&tenant_id=&depth=` redirects to `/graph` with the same params.
5. Alias `entity` / `tenant` query params seed the workspace.

## Out of scope

- Ontology / schema editor (`PUT /schema` stays as today; this UI is read-only chips)
- Timeline, map, comments, pins, saved views
- vis-network
- Elasticsearch / property-bag search
- New investigation-agent or Shadow tool
- Auto-loading full community/ring membership onto the canvas
- Decision-api reading stored scores
- Inventing graph when the plane is down
