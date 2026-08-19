# Tarka documentation hub

Canonical operator docs. Prefer these over wiki mirrors or old status dumps.

## Audiences

| Audience | Start here |
|----------|------------|
| **Strategy analyst** — author a pack (JSON rules) | [15-minute first decision](docs/guides/oss-15-minute-first-decision.md) · [Quickstart](docs/quickstart.md) · [Rule authoring](docs/guides/rules.md) |
| **Investigator** — open a case (`/cases` + pack-why) | [15-minute first decision](docs/guides/oss-15-minute-first-decision.md) · [Quickstart](docs/quickstart.md) · [Cases / SAR flows](docs/guides/feature-data-flows.md#3-cases-brief-sar) |

| Topic | Start here |
|-------|------------|
| **Evaluate** | [Feature data flows](docs/guides/feature-data-flows.md) · [architecture](docs/architecture.md) · [decision-api](../services/decision-api/README.md) · [STUB_REGISTER](STUB_REGISTER.md) |
| **Graph** | [service-ports](docs/guides/service-ports.md) · Janus demo `infra/deploy/janusgraph-cassandra-demo/` · `GRAPH_BACKEND` · [Decision context graph](docs/guides/decision-context-graph.md) |
| **Observe** | observe-only evaluate (`metadata.shadow`) · pack **Canary** · [shadow mode / A/B](docs/guides/shadow-and-ab-testing.md) |
| **Advise** | [services/SHADOW.md](../services/SHADOW.md) · Shadow agent · ingest `shadow_agent` · desktop `tools/shadow` (specialist tool, not a third product) |
| **Cases / SAR** | case-api + [feature data flows §3](docs/guides/feature-data-flows.md#3-cases-brief-sar) |
| **Deploy / SRE** | [SRE Compose profiles](docs/operations/sre-compose-profiles.md) · [quickstart](docs/quickstart.md) · [productionization](docs/guides/repo-productionization-runbook.md) |
| **MkDocs site** | `docs/docs/` + `docs/mkdocs.yml` (`mkdocs serve` from `docs/`) |

## Compose (one story)

```bash
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.fraud-desk.yml \
  up --build
```

Same command as the README. Lab / legacy files (`v2-ingest`, graph-wire, streams-ai, …) live under `infra/deploy/archive/`.

## Wiki

[`wiki/`](../wiki/) mirrors [GitHub wiki](https://github.com/pamu512/tarka/wiki) (separate repo; may lag until maintainers run [`scripts/docs/sync-github-wiki.sh`](../scripts/docs/sync-github-wiki.sh)). If wiki and this hub disagree, **trust this hub and the code**.
