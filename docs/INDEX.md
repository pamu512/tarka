# Tarka documentation hub

Canonical operator docs. Prefer these over wiki mirrors or old status dumps.

| Topic | Start here |
|-------|------------|
| **Evaluate** | [Feature data flows](docs/guides/feature-data-flows.md) · [architecture](docs/architecture.md) · [decision-api](../services/decision-api/README.md) · [STUB_REGISTER](../STUB_REGISTER.md) |
| **Graph** | [service-ports](docs/guides/service-ports.md) · Janus demo `infra/deploy/janusgraph-cassandra-demo/` · `GRAPH_BACKEND` · [Decision context graph](docs/guides/decision-context-graph.md) |
| **Shadow** | [services/SHADOW.md](../services/SHADOW.md) · ingest `shadow_agent` · desktop `tools/shadow` |
| **Cases / SAR** | case-api + [feature data flows §3](docs/guides/feature-data-flows.md) |
| **Deploy / SRE** | [SRE Compose profiles](docs/docs/operations/sre-compose-profiles.md) · [quickstart](docs/quickstart.md) · [productionization](docs/guides/repo-productionization-runbook.md) |
| **MkDocs site** | `docs/docs/` + `docs/mkdocs.yml` (`mkdocs serve` from `docs/`) |

## Compose (one story)

1. Desk: `docker compose -f infra/deploy/docker-compose.lite.yml -f infra/deploy/docker-compose.fraud-desk.yml up --build`
2. Ingest rail: `infra/deploy/docker-compose.v2-ingest.yml`
3. Trend: `--profile trend-tick` or `make trend-tick`

## Wiki

[`wiki/`](../wiki/) is a short GitHub wiki mirror of the same story. If wiki and this hub disagree, **trust this hub and the code**.
