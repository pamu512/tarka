# Tarka documentation hub

Canonical operator docs.

## Audiences

| Audience | Start here |
|----------|------------|
| **Strategy analyst** — author and promote packs (JSON rules) | [15-minute first decision](docs/guides/oss-15-minute-first-decision.md) · [Quickstart](docs/quickstart.md) · [Rule authoring](docs/guides/rules.md) · [Observe / promote](docs/guides/shadow-and-ab-testing.md) · [Backtest before promote](docs/guides/backtest-before-promote.md) |
| **Investigator** — work the Person on Hunt; leftovers are the thin station | [15-minute first decision](docs/guides/oss-15-minute-first-decision.md) · [Feature data flows](docs/guides/feature-data-flows.md) |

Investigators do not author rules; strategy analysts do. Work **arrives** on `/leftovers`. Work **happens** on Hunt (`/graph`). Fat `/cases` stays hidden in lean. ALLOW never becomes a leftover.

## Topics

| Topic | Start here |
|-------|------------|
| **Evaluate (decision stream)** | [Feature data flows](docs/guides/feature-data-flows.md) · [architecture](docs/architecture.md) · [decision-api](../services/decision-api/README.md) |
| **Graph / Hunt (required for the desk)** | Lite Day-1 is Apache AGE on the same Postgres + `graph-service`. Wire another graph with `GRAPH_SERVICE_URL` + `GRAPH_BACKEND`. Empty URL is evaluate-only fallback (home `/decisions`), not the product. Evaluate never waits on graph. [service-ports](docs/guides/service-ports.md) · [Decision context graph](docs/guides/decision-context-graph.md) |
| **Leftovers** | Thin station `GET /v1/leftovers` + desk `/leftovers`. Hold / resolve stay on Hunt. |
| **Observe** | Pack canary + leftover promote + live-rule slip on `/ops/shadow` (always-on lean). RFP "shadow mode" = Observe evaluate (`metadata.shadow`) only — not the LLM. [Shadow / A/B guide](docs/guides/shadow-and-ab-testing.md). |
| **Advise (optional)** | [services/SHADOW.md](../services/SHADOW.md) · Shadow agent LLM · BYO Azure OpenAI / Vertex / Bedrock / Claude / Qwen / in-cluster vLLM. Off until operator wires `SHADOW_AGENT_URL`. |
| **Cases (residual / SAR)** | case-api + [feature data flows §3](docs/guides/feature-data-flows.md#3-leftovers-hunt-brief-sar). Leftover list is not fat `/cases`. |
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
docker compose -f infra/deploy/docker-compose.lite.yml up --build
```

Lite Day-1 is evaluate **plus** AGE graph (same as the README). Thin desk: add `-f infra/deploy/docker-compose.fraud-desk.yml` (Hunt home `/graph`, leftovers, `/ops/shadow`). Investigation / signals / Janus overlay: [SRE compose profiles](docs/operations/sre-compose-profiles.md). Lab files (`v2-ingest`, graph-wire) live under `infra/deploy/archive/`.
