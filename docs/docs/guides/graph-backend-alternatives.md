# Graph backend alternatives (Apache-friendly options)

Neo4j **Community Edition** is **AGPL-licensed**. Tarka documents that in **`LICENSE-DEPENDENCIES.md`** and offers a **lite** compose path **without** Neo4j for quick evaluation.

If you need a **default graph** that stays in the **Apache-2.0 / permissive** ecosystem, consider:

| Backend | Notes |
|---------|--------|
| **[FalkorDB](https://www.falkordb.com/)** | Redis module, Cypher subset; good for smaller graphs and OSS-friendly licensing (verify current license for your version). |
| **[Memgraph](https://memgraph.com/)** | Cypher-compatible; enterprise features may be commercial; check license for self-hosted OSS tier. |
| **JanusGraph** | Already referenced in deployment docs as a long-term HA alternative to Neo4j Community. |

## What would change in Tarka

- **`graph-service`** today speaks **Neo4j Bolt** via the official driver. A new backend requires:
  - A **driver adapter** (connection, Cypher translation or query rewrite, transaction semantics).
  - **Compose / Helm** image swaps and health checks.
  - **CI** integration tests against that backend (container service).

This is **not** switched on by default in the repository yet; treat this file as the **integration checklist** when you open a `graph-backend-*` issue.

## Lite stack

**`deploy/docker-compose.lite.yml`** intentionally omits graph infrastructure; use **mock/UI** paths or spin up **full** compose when you need live graph features.
