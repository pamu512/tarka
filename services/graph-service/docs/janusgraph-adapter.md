# JanusGraph backend (same HTTP API as Neo4j)

The graph service exposes a **single** REST contract (`/v1/entities`, `/v1/links`, `/v1/subgraph`, `/v1/analytics/*`). Callers (Decision API, Case UI, investigation / AI copilot) **do not change** when you switch backends—only **environment variables** and the deployed graph change.

## Switching backends

| Variable | Default | Meaning |
|----------|---------|---------|
| `GRAPH_BACKEND` | `janusgraph` | `neo4j` (Bolt + Cypher), `janusgraph` (Gremlin Server), or `age`. |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | — | Used when `GRAPH_BACKEND=neo4j`. |
| `JANUSGRAPH_GREMLIN_URL` | `ws://localhost:8182/gremlin` | WebSocket URL to Gremlin Server when `GRAPH_BACKEND=janusgraph`. |
| `JANUSGRAPH_TRAVERSAL_SOURCE` | `g` | Traversal source name on the server. |
| `JANUSGRAPH_ANALYTICS_VERTEX_CAP` | `8000` | Upper bound on vertices loaded into memory for Janus-side analytics **and** search fallback when mixed index `vertexSearch` is not ENABLED (100–500000). |

No code changes are required in downstream services: keep `GRAPH_SERVICE_URL` pointed at this service.

## Ontology (unchanged)

Vertices use labels from the allow-list (`Person`, `Account`, `Device`, `Payment`, `Document`, `Custom`) plus tenant-specific types from the schema store. Every vertex has `tenant_id` and `external_id`.

Edges use relationship names (`USED`, `SHARED_WITH`, …) or tenant-specific names from schema; unknown names sanitize to `RELATED`.

On JanusGraph, **tags** are stored as a **JSON array string** on a single property `tags` (Neo4j may use a native list); the HTTP API still returns `tags` as a JSON list.

Entity upserts return `graph_id`: Neo4j returns `elementId`; JanusGraph returns a stable synthetic id `jvg:{tenant_id}:{external_id}`.

## JanusGraph / Gremlin Server expectations

1. Run **Gremlin Server** reachable at `JANUSGRAPH_GREMLIN_URL` (WebSocket).
2. Bind a **global traversal source** (typically `g`) matching `JANUSGRAPH_TRAVERSAL_SOURCE`.
3. **Indexes (created on first graph-service connect, and the same Groovy is mounted in the Cassandra demo):**
   - Unique composite `byTenantExternal` on `(tenant_id, external_id)`. Lookups stay `has("tenant_id").has("external_id")`. REGISTERED/INSTALLED does not block HTTP (unique indexes will not ENABLE while duplicates exist).
   - Mixed index `vertexSearch` on backend `search` (demo Lucene: `index.search.backend = lucene`): `tenant_id` STRING, allowlisted search keys TEXTSTRING (`external_id`, `email`, `device_id`, `address`, `line1`, `phone`, `ip`, `user_id`, `card_id`).
4. **Search:** JanusGraph is case-insensitive **prefix** (`textContainsPrefix` + Python `startswith` re-check). Neo4j/AGE remain CONTAINS. If `vertexSearch` is not ENABLED, search scans at most `JANUSGRAPH_ANALYTICS_VERTEX_CAP` vertices and sets `truncated: true` when that cap is hit.
5. **GRAPH_INGEST** stamps `tenant_id` from `metadata.tenant_id` and `external_id` equal to the native key (`device_id`, `email`, …). Missing tenant → no Gremlin write (`reason=no_tenant`). Vertices that still lack `tenant_id`/`external_id` miss typeahead and cannot seed subgraph.
6. **Subgraph / deep-context:** one Gremlin round-trip per depth layer. Super-node neighborhoods can be large in RAM (no silent per-vertex edge cap).

## Analytics parity notes (JanusGraph)

When `GRAPH_BACKEND=janusgraph`, analytics use Gremlin plus in-process graph algorithms (`networkx` for cycle basis, union-find for components, etc.). Results are **intended to be compatible** with the Neo4j responses (same JSON shapes), but:

- **Fraud rings** (`/v1/analytics/fraud-rings`) use an **approximation** (cycle basis / simple cycles in an exported subgraph), not the same Cypher simple-cycle enumeration as Neo4j. Treat as operationally similar, not bit-identical.
- Heavy analytics are **capped** by `JANUSGRAPH_ANALYTICS_VERTEX_CAP`; raise the cap only with enough heap and monitoring.

## Hardening checklist (operators)

- TLS termination in front of Gremlin Server where exposed beyond localhost.
- Auth on Gremlin Server (if supported by your stack) or network policy restricting the graph service → Gremlin path only.
- Rate limits and timeouts at the API gateway in front of graph-service (unchanged from Neo4j deployments).
- Backups and restore procedures for your JanusGraph storage backend (Cassandra, Scylla, etc.) per your vendor runbook.

## Local smoke (optional)

With JanusGraph + Gremlin listening on `ws://localhost:8182/gremlin`:

```bash
set GRAPH_BACKEND=janusgraph
set JANUSGRAPH_GREMLIN_URL=ws://localhost:8182/gremlin
uvicorn graph_service.main:app --host 0.0.0.0 --port 8085 --app-dir src
```

Then exercise `POST /v1/entities`, `POST /v1/links`, `GET /v1/subgraph` as with Neo4j.
