# Third-party licenses and compliance notes

Tarka **application code** is source-available under the **Elastic License 2.0** (see [`LICENSE`](LICENSE)). This file is only for **third-party runtimes and libraries** (Apache AGE, Postgres, optional JanusGraph / Neo4j, drivers, SDKs). Those keep their own licenses. AGE is Apache-2.0; it is not ELv2.

This file highlights **license implications** for major runtime dependencies and **default deployment choices**. It does not replace the full SPDX / lockfile inventory—use your organization’s SBOM process for audits.

## Graph database (Neo4j)

The **full** `infra/deploy/docker-compose.yml` stack can run **Neo4j** (`neo4j` Docker image) for `graph-service`.

- **Neo4j Community Edition** (typical OSS deployment) is licensed under the **[GNU Affero General Public License v3 (AGPL-3.0)](https://neo4j.com/licensing/)** for the database **when you run it as a networked service**. AGPL has **copyleft and network** obligations that may affect how you distribute or offer Tarka as a service.
- **Neo4j Enterprise** is commercial.
- The **Python driver** (`neo4j` PyPI package) used by `graph-service` is **Apache License 2.0**—the driver license is not the same as the database license.

### Permissive-licensed graph runtimes (AGE / JanusGraph)

These alternatives are about **dependency** licenses, not Tarka’s. If Neo4j AGPL is incompatible with your policy:

1. **`infra/deploy/docker-compose.lite.yml`** — **Apache AGE** (`apache/age`, `GRAPH_BACKEND=age`) on the same Postgres as evaluate. No Neo4j, no Janus JVM. Helm `fraud-stack` defaults to the same backend.
2. **JanusGraph** — Apache-2.0; still available via `GRAPH_BACKEND=janusgraph` on the full compose / Gremlin overlay.
3. **Memgraph** or **FalkorDB** — evaluate separately; Cypher compatibility differs. Not wired today.

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
