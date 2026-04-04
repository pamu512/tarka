# Third-party licenses and compliance notes

This file highlights **license implications** for major runtime dependencies and **default deployment choices**. It does not replace the full SPDX / lockfile inventory—use your organization’s SBOM process for audits.

## Graph database (Neo4j)

The **full** `deploy/docker-compose.yml` stack can run **Neo4j** (`neo4j` Docker image) for `graph-service`.

- **Neo4j Community Edition** (typical OSS deployment) is licensed under the **[GNU Affero General Public License v3 (AGPL-3.0)](https://neo4j.com/licensing/)** for the database **when you run it as a networked service**. AGPL has **copyleft and network** obligations that may affect how you distribute or offer Tarka as a service.
- **Neo4j Enterprise** is commercial.
- The **Python driver** (`neo4j` PyPI package) used by `graph-service` is **Apache License 2.0**—the driver license is not the same as the database license.

### Apache-2.0–friendly alternatives (recommended for strict OSS stacks)

If AGPL is incompatible with your policy:

1. **`deploy/docker-compose.lite.yml`** — **does not start Neo4j**; graph features are off (`GRAPH_SERVICE_URL` empty). Use this for quick demos and minimal compliance surface.
2. **Memgraph** or **FalkorDB** (and similar) — evaluate separately; **API and Cypher compatibility differ** from Neo4j. Swapping backends requires code and query review (not a one-line change today). See **`docs/docs/guides/graph-backend-alternatives.md`** for a short integration checklist.

**Action for operators:** Choose **lite** or a **non-AGPL graph backend** explicitly in architecture reviews; do not assume “open source graph” implies a permissive DB license.

## Other notable components

| Area | Typical dependency | License (indicative) |
|------|-------------------|----------------------|
| API framework | FastAPI, Starlette | MIT |
| ORM / DB | SQLAlchemy, asyncpg | MIT / PostgreSQL |
| ML inference | ONNX Runtime (if used) | ONNX license / MIT components |
| Cloud KMS SDKs | AWS / GCP / Azure SDKs | Apache-2.0 |

Verify versions in each service’s `pyproject.toml` / lockfile at build time.

## OSINT and external APIs

`integration-ingress` can call **third-party OSINT and KYC APIs**. Those services have **their own terms**; API keys are operator-supplied. No keys are required for unit tests (mocks/stubs).

## Disclaimer

This document is **informational**, not legal advice. Consult counsel for AGPL/network copyleft and for your deployment topology.
