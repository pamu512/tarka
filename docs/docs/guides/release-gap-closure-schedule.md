# Critical gap closure — what ships when

Maps [competitive-critical-review-2026-04.md](./competitive-critical-review-2026-04.md) / [tarka-gap-code-map.md](./tarka-gap-code-map.md) to **`v1.1.0` (2026-04-30)** and **`v1.2.0` (2026-05-30)**.

## v1.1.0 (2026-04-30) — ship checklist (engineering)

| Gap | Closure |
|-----|---------|
| Inference contract / calibration shell | **`inference_context` v2** + **`contracts/golden/`** + pytest golden-key parity |
| “Specs drift from code” | **OpenAPI YAML parse + structure checks** + **FastAPI** schema smoke in **decision-api** tests (tighten to full OAS 3.1 later) |
| Agent trust | **Tenant-scoped tool calls** tests + **prompt-injection** / **output redaction** tests |
| “No graph proof” | **Optional CI job** with **live Neo4j** Bolt smoke (`NEO4J_INTEGRATION=1`) |
| Operational proof | **Prometheus/Grafana add-on**, **`latency_evaluate.py`**, **simulation A/B** docs (already in API) |
| DB operations | **Alembic** on Postgres for decision/case APIs |

**Tag when:** CI green (including new jobs), release note acceptance bullets satisfied.

## v1.2.0 (2026-05-30) — ship checklist (engineering)

**Doc vs code:** rolling honesty table in [`releases/v1.2.0-2026-05-30.md`](../releases/v1.2.0-2026-05-30.md) § *Documentation vs code (rolling tracker)* — update when features land.

| Gap | Closure |
|-----|---------|
| Counter / velocity maturity | **Feature-service** multi-window counters, normalized velocity keys per roadmap |
| Online/offline parity | **[counter-replay-parity.md](./counter-replay-parity.md)** + `replay_aggregates.py` + `diff_aggregate_redis.py` + **CI** `test_golden_counters.py` |
| Challenge / FP friction | **Policy templates** — JSON under `rules/challenge_policies/`, `challenge_policy_id` on evaluate, **`GET /v1/challenge-policies`**, extends `recommended_action` |
| Connector seriousness | **Ingress reliability** scorecards + UI/API fields |
| Benchmarks | **Vertical packs** + reproducible harness; publish **hey/k6** numbers using [`scripts/benchmarks/`](../../scripts/benchmarks/README.md) |
| Load discipline | Optional **scheduled workflow** or documented **hey** SLO runbook |

**Tag when:** Day 60 acceptance tests in [`roadmap-30-60-90.md`](./roadmap-30-60-90.md) pass; examples updated for new packs.

## Still after v1.2 (v1.3.0 or later)

- Full **calibration** pipeline (reliability diagrams, drift monitors).
- **NATS → Prometheus** via exporter.
- **Alternate graph backend** ([graph-backend-alternatives.md](./graph-backend-alternatives.md)).
- **Contract fuzz** (e.g. Schemathesis) on running containers — optional stretch beyond static OpenAPI validation.
