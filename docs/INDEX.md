# Tarka docs hub (triad-shaped)

Canonical operator index. Prefer these over scattered epic status notes.

| Pillar | Start here | Avoid |
|--------|------------|-------|
| **Evaluate** (Rust / decision-api) | [Root ARCHITECTURE.md](../ARCHITECTURE.md) · [one Rust rule engine spec](superpowers/specs/2026-07-11-one-rust-rule-engine-design.md) · [decision-api README](../services/decision-api/README.md) | Python `rule_engine` HTTP evaluate; quarantined `core_v2` |
| **Graph** (JanusGraph / Gremlin) | [service-ports](docs/guides/service-ports.md) · [graph contract](../services/decision-api/docs/decision-api-graph-service-contract.md) · janusgraph demo under `infra/deploy/janusgraph-cassandra-demo/` | Treating Neo4j/AGE forks as peers without `GRAPH_BACKEND` |
| **Shadow** (local forensics) | [services/SHADOW.md](../services/SHADOW.md) · ingest `shadow_agent` · desktop `tools/shadow` | A fourth HTTP “Shadow” service |
| **Cases** | case-api + analyst SPA [`frontend/`](../frontend/) | Prototype Notifications inbox (removed) |
| **Deploy** | Root `docker-compose.yml` (Lite) · [`infra/deploy/docker-compose.yml`](../infra/deploy/docker-compose.yml) profiles · Helm `infra/deploy/helm/fraud-stack/` · [archive](../infra/deploy/archive/README.md) | Archived `single` / `lite.smoke` / broken host-ports overlays |

## Other hubs

- MkDocs site home: [`docs/index.md`](docs/index.md)
- Repo layout: [`REPOSITORY_LAYOUT.md`](REPOSITORY_LAYOUT.md)
- Stub honesty: [`../STUB_REGISTER.md`](../STUB_REGISTER.md)
- Product vision / ROI: complexity canvas in Cursor (Jul 2026)

## Compose (one story)

1. `docker compose up` → Lite / `core-api`
2. Profiles / full modular → `infra/deploy/docker-compose.yml`
3. Ingest rail → `infra/deploy/docker-compose.v2-ingest.yml`
4. Legacy streams → `docker-compose.streams-ai.yml` only
