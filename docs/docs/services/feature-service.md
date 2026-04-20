# Feature Service

Velocity reads and canonical feature snapshots over **Redis-backed aggregates** aligned with the Decision API counter keyspace. Used for analyst tooling, governance “Feature tools,” and **golden parity** checks against evaluate-time materialization.

**Port:** 8004  
**Framework:** Python / FastAPI

---

## Highlights

| Concern | Entry point |
|---------|-------------|
| Multi-window velocity | `POST /v1/velocity/query` — see [API Reference — Feature Service](../api-reference.md#feature-service) |
| Parity gate (OSS #48) | `POST /v1/internal/parity/verify` — compare live counters to `expected` within `epsilon` (**200** vs **409** drift) |
| Canonical snapshot | `POST /v1/snapshot` — feature vector for ML/rules enrichment |
| SLO / health | `GET /v1/slo`, `GET /v1/health` |

!!! note "Contract"

    OpenAPI: `contracts/openapi/feature-service.yaml`  
    Deeper narrative: [Feature Service project](../projects/feature-service-project.md), [Typology / parity / checkpoints guide](../guides/oss-typology-parity-graph-34-48-49.md).

---

## Configuration

Set **`REDIS_URL`** or **`FEATURE_SERVICE_REDIS_URL`** to the **same Redis** as the Decision API when you need velocity reads and parity to match production aggregates. Without Redis, velocity and parity endpoints return **503**.
