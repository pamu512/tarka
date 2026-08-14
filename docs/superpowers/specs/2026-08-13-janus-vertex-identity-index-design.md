# Janus vertex identity + composite index

**Date:** 2026-08-13  
**Status:** Approved  
**Related:** [property search](./2026-08-13-graph-property-search-design.md), [janusgraph-adapter](../../../services/graph-service/docs/janusgraph-adapter.md)

Ladder rungs **1 and 2** only. Rungs 3–5 (mixed indexes / `textContainsPrefix`, `valueMap` rewrite, search cap + owner dedupe) are follow-on specs.

## Goal

Ingest vertices become the same objects graph-service already searches and seeds: **`tenant_id` + `external_id`**. Janus lookups stop depending on an unindexed full-graph `has(tenant_id).has(external_id)` once a **unique composite index** exists.

## Philosophy (unchanged)

- Decision-api / rules remain sole allow/deny.
- Do not invent graph, nodes, `entity_id`, `tenant_id`, or scores.
- Empty / missing tenant → no ingest write (not `demo`, not a guessed tenant).
- `0` is a computed clean score. Unscored stays `null`.

## What already exists

- graph-service upsert: `addV(label).property(tenant_id).property(external_id)`; merge by those two props, unique per tenant across labels.
- GRAPH_INGEST (`graph_ingest.py`) and `JanusGraphClient._merge_vertex`: `has(label, key_prop, key_val)` with **no** `tenant_id` / `external_id`. Those vertices are skipped by search and cannot seed subgraph.
- Tenant on the envelope is `metadata.tenant_id` (same as evaluate).
- Demo `janusgraph.properties` enables Lucene; **no** composite index is created in code.
- `JANUSGRAPH_ANALYTICS_VERTEX_CAP` caps analytics, not search.

## Identity (rung 1)

**Writers to change:** `services/orchestrator/workers/handlers/graph_ingest.py` `_merge_vertex` and `services/orchestrator/graph/client.py` `JanusGraphClient._merge_vertex`. Shared helper preferred if both can import it without a cycle; otherwise duplicate the lookup/stamp (ponytail: two copies of ~20 lines, not a new package).

**Tenant:** `str(metadata.get("tenant_id") or "").strip()`. If empty: log `graph_ingest_noop … reason=no_tenant`, return success without Gremlin writes (outbox does not retry). Do not invent a tenant.

**Stamp on every merged vertex:**

| Label | Native key (kept) | `external_id` |
|-------|-------------------|---------------|
| User | `user_id` | same value |
| Device | `device_id` | same value |
| IP | `address` | same value |
| Card | `card_id` | same value |
| Email | `email` | same value |
| Address | `line1` | same value |
| Listing | `listing_id` | same value |

**Lookup order:**

1. `g.V().has("tenant_id", tenant).has("external_id", key_val).limit(1)`
2. Else `g.V().has(label, key_prop, key_val).limit(1)` (legacy ingest vertex)
3. Else `addV(label).property(key_prop, key_val)`

Then always `property(Cardinality.single, "tenant_id", tenant)` and `property(Cardinality.single, "external_id", key_val)` and keep the native key. Existing `tarka_audit_log_id` idempotency on GRAPH_INGEST is unchanged.

**Collision:** `(tenant_id, external_id)` is unique across labels (already graph-service contract). A User `user_id` equal to a Device `device_id` merges onto one vertex. No `{label}:` prefix.

**No backfill job.** The next ingest that sees a legacy vertex stamps it.

**Edge resolves** that today use `has(LABEL_DEVICE, "device_id", …)` may keep that lookup in this spec (legacy still works). New vertices are also findable by `external_id`.

**Neo4j ingest** in `GraphClient` (Cypher MERGE on native keys) is **out of scope**.

## Composite index (rung 2)

**Name:** `byTenantExternal`  
**Type:** unique composite index on `Vertex` for property keys `tenant_id` (String) and `external_id` (String).

**graph-service** (`GRAPH_BACKEND=janusgraph` only), on first Gremlin connect:

- Open a Gremlin **Client** (script submit), not only `DriverRemoteConnection` traversal.
- Submit Groovy that: get-or-create both property keys; if index `byTenantExternal` missing, `buildIndex(…).addKey(tenant_id).addKey(external_id).unique().buildCompositeIndex()`; `commit`.
- If the index already exists / status ENABLED: no-op.
- If status is REGISTERED or INSTALLED: **do not block HTTP**. Log a warning; operator reindex. Unique indexes will not ENABLE while duplicates exist.
- Failure to talk to mgmt: log error, continue serving (lookups stay correct, still slow).

**Demo:** same Groovy mounted/run at JanusGraph container start (`infra/deploy/janusgraph-cassandra-demo/`) so empty clusters have keys+index without waiting for graph-service.

Lookups stay `has("tenant_id").has("external_id")`. Once ENABLED, Janus uses the index. No mixed indexes. No search rewrite.

## Errors

- Missing tenant: skip ingest, log `no_tenant`, outbox complete.
- Gremlin down: existing `GraphDatabaseConnectionError` / connection retry.
- Index not ENABLED: warn, serve.
- Do not invent `external_id` from a blank native key (existing `_safe_graph_key` / hint parsing still drops empty keys).

## Tests

1. Missing `metadata.tenant_id` → `_merge_vertex` / Gremlin not called.
2. Tenant present → merged Device has `tenant_id`, `external_id == device_id`, and `device_id` still set. Same for Email (`email`).
3. Legacy vertex (only `device_id`) is found and stamped with tenant + `external_id` on merge.
4. `JanusGraphClient._merge_vertex` source or unit test: writes `tenant_id` and `external_id`.
5. Index ensure script/source contains `byTenantExternal`, `tenant_id`, `external_id`, `unique`. Idempotent when the name already exists (branch or string). No live Janus in CI.
6. Docs: `janusgraph-adapter.md` states ingest stamps identity and graph-service/demo create `byTenantExternal` (not “recommended for production” only).

## Out of scope

- Mixed indexes, `textContains` / `textContainsPrefix`, search Python-scan rewrite
- `valueMap` / single-traversal subgraph, `both().limit(10)`
- Search vertex cap, `(via, owner)` dedupe
- Inventing `entity_id` or tenant
- Full-graph backfill
- Elasticsearch
- Neo4j/AGE ingest identity
- Changing unique-across-labels merge in graph-service upsert
