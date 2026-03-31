# Optional JanusGraph / Gremlin adapter

The HTTP API in this repository is the **contract** for Tarka. The default implementation uses **Neo4j** and the Bolt driver.

To use an Apache-2.0-friendly graph backend:

1. Deploy **JanusGraph** (or compatible Gremlin server).
2. Implement the same routes (`POST /v1/entities`, `POST /v1/links`, `GET /v1/subgraph`) in a new service (e.g. `graph-service-gremlin`).
3. Map the reference ontology to vertex labels and edge labels:
   - Vertices: `Person`, `Account`, `Device`, `Payment`, `Document`, `Custom` + properties `tenant_id`, `external_id`.
   - Edges: `USED`, `SHARED_WITH`, `REFERRED`, `KYC_VERIFIED_BY`, `OWNS`, `CUSTOM`, `RELATED`.
4. Point `GRAPH_SERVICE_URL` at the new service from Decision API and Case UI.

Gremlin examples (conceptual):

- Upsert vertex: `g.V().has('Account','external_id', id).fold().coalesce(unfold(), addV('Account').property('external_id', id))`
- Subgraph: repeat `bothE().otherV()` for bounded depth from the root vertex.
