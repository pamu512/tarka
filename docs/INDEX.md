# Tarka documentation hub

Canonical operator docs. Prefer these over wiki mirrors or old status dumps.

## Audiences

| Audience | Start here |
|----------|------------|
| **Strategy analyst** — author and promote packs (JSON rules) | [15-minute first decision](docs/guides/oss-15-minute-first-decision.md) · [Quickstart](docs/quickstart.md) · [Rule authoring](docs/guides/rules.md) · [Backtest before promote](docs/guides/backtest-before-promote.md) |
| **Investigator** — read which pack fired and why on an evaluate-born residual case | [Quickstart](docs/quickstart.md) · [Feature data flows](docs/guides/feature-data-flows.md) |

Investigators do not author rules; strategy analysts do. Cases are residual: born from evaluate → review / deny. ALLOW never becomes a case.

## Topics

| Topic | Start here |
|-------|------------|
| **Evaluate (decision stream)** | [Feature data flows](docs/guides/feature-data-flows.md) · [architecture](docs/architecture.md) · [decision-api](../services/decision-api/README.md) · [STUB_REGISTER](STUB_REGISTER.md) |
| **Graph (optional)** | [service-ports](docs/guides/service-ports.md) · Janus demo `infra/deploy/janusgraph-cassandra-demo/` · `GRAPH_BACKEND` · [Decision context graph](docs/guides/decision-context-graph.md) |
| **Observe** | Observe-only evaluate (`metadata.shadow`) + pack **Canary**. RFP "shadow mode" = Observe only. [Shadow / A/B guide](docs/guides/shadow-and-ab-testing.md). |
| **Advise (optional)** | [services/SHADOW.md](../services/SHADOW.md) · Shadow agent LLM · BYO Azure OpenAI / Vertex / Bedrock / Claude / Qwen / in-cluster vLLM. Off until operator wires `SHADOW_AGENT_URL`. |
| **Cases (residual)** | case-api + [feature data flows §3](docs/guides/feature-data-flows.md#3-cases-brief-sar). Cases are born from evaluate review/deny, not intake. |
| **Deploy / SRE** | [SRE Compose profiles](docs/operations/sre-compose-profiles.md) · [quickstart](docs/quickstart.md) · [productionization](docs/guides/repo-productionization-runbook.md) |
| **MkDocs site** | `docs/docs/` + `docs/mkdocs.yml` (`mkdocs serve` from `docs/`) |

## QA: two separate loops

1. **Blind predetermined-N evaluate events** — HIL confirms the engine. Schedulable; skip only if no drift.
2. **Second-human sample of cases already closed by HIL** — existing `qa_sample_closed_cases` / `/ops/qa`.

Do not collapse them into one workflow. Do not invent review rates.

## Product locks

- **Skip does not block.** Skipping or avoiding a risk check raises showing-signs risk; it does not hard-block.
- **Entity states** — proven / already-risky · showing-signs · unknown. Device is a node, not the person. ATO victims stay good.
- **Visual rule builder** is stretch, not the product. Strategy analysts author JSON packs.
- **No Tarka-branded model.** Advise is BYO LLM.

## Compose (one story)

```bash
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.fraud-desk.yml \
  up --build
```

Same command as the README. Lab / legacy files (`v2-ingest`, graph-wire, streams-ai, …) live under `infra/deploy/archive/`.

## Wiki

[`docs/wiki/`](wiki/) mirrors [GitHub wiki](https://github.com/pamu512/tarka/wiki) (separate repo; may lag until maintainers run [`scripts/docs/sync-github-wiki.sh`](../scripts/docs/sync-github-wiki.sh)). If wiki and this hub disagree, **trust this hub and the code**.
