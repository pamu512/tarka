# Tarka

Tarka is a local-first fraud OS: evaluate packs + audit trail + analyst desk.

**Status:** beta. There is no GA tag. Development is on `master`.

## Day-1 (compose)

Lite is evaluate + graph (Rust packs + `core-api` + Apache AGE). Wire your own graph by pointing `GRAPH_SERVICE_URL` / `GRAPH_BACKEND` at it. Thin desk overlay is optional. Same path as [`docs/INDEX.md`](docs/INDEX.md) and the [15-minute first decision](docs/docs/guides/oss-15-minute-first-decision.md). Profiles: [SRE compose runbook](docs/docs/operations/sre-compose-profiles.md).

```bash
docker compose -f infra/deploy/docker-compose.lite.yml up --build
# thin desk (Hunt /graph + /rules; receipts at /decisions):
#   -f infra/deploy/docker-compose.fraud-desk.yml
# + investigation / + signals / full desk: see the SRE runbook
```

Desk home is `/graph` when graph is on. Receipts stay at `/decisions`.

- [Author a pack](docs/docs/guides/rules.md) — JSON rule packs (strategy analyst)
- [First evaluate](docs/docs/guides/oss-15-minute-first-decision.md) — `POST /decisions/v1/decisions/evaluate`

```
Can-run
Compose fraud-desk is day-1.
Helm prod-on-k8s is core-api HA
(replicaCount 2, tenant binding on).
investigation-agent ON (postgres, 2 replicas).
frontend / desk OFF.
Shadow OFF (no model in the chart;
operator BYO URL later, no Tarka-branded model).
OIDC optional.
```

**Docs:** [`docs/INDEX.md`](docs/INDEX.md) · [`SECURITY.md`](SECURITY.md) · [`SUPPORT.md`](SUPPORT.md) · [`CONTRIBUTING.md`](CONTRIBUTING.md)

Operator CLI (optional): `python3 cli.py` or compose under `infra/deploy/`.

---

## Vision (below the fold)

Manifesto, evaluate-first product lock, Advise / local inference, and entity-state notes live in [`VISION.md`](VISION.md). Day-1 is the compose path above — not a laptop triad and not an enterprise desk.

Graph is on Day-1 (Tarka AGE, or yours). Optional after that: investigation overlay, signals overlay, local Advise/Ollama. Size them from the [SRE compose runbook](docs/docs/operations/sre-compose-profiles.md).

**15-minute first decision:** [docs/docs/guides/oss-15-minute-first-decision.md](docs/docs/guides/oss-15-minute-first-decision.md) → `python3 scripts/oss/first_decision_smoke.py`

---

## Performance

Reproduce **local** figures only from this README. Hypothetical scale-out projections (if any) live exclusively in [`scripts/benchmarks/README.md`](scripts/benchmarks/README.md) and must never be cited as shipped SLOs.

```bash
python scripts/benchmarks/vertical_benchmark_smoke.py --seed 42 --threshold strict
```

Also see [`latency_evaluate.py`](scripts/benchmarks/latency_evaluate.py). Publish host SKU, compose profile, commit SHA, warm-up count, payload schema.

---

## Repository map

| Path | Role |
|------|------|
| [`frontend/`](frontend/) | React analyst app |
| [`services/`](services/) | Microservices — `core-api` / decision-api, orchestrator, `shadow_agent`, investigation-agent (Observe vs Advise: [`services/SHADOW.md`](services/SHADOW.md)) |
| [`packages/`](packages/) | Internal libs (`deploy-settings`, `shared-core`, SDKs) |
| [`infra/`](infra/) | `infra/deploy/` (Compose, Helm, OPA) + `infra/scripts/` |
| [`docs/`](docs/) | Operator hub [`docs/INDEX.md`](docs/INDEX.md) |
| [`crates/tarka-core/`](crates/tarka-core/) | Rust decision DAG / determinism |
| [`crates/tarka-cli/`](crates/tarka-cli/) | `tarka replay` |

---

## License

Tarka application code is **source-available** under the **Elastic License 2.0**. You may `git clone`, modify, and run Tarka on your own metal or VPC for your own fraud operations. You may not provide Tarka to third parties as a hosted or managed service.

Third-party graph/database runtimes (Apache AGE, Postgres, optional Janus/Neo4j) keep their own licenses — see [`LICENSE-DEPENDENCIES.md`](LICENSE-DEPENDENCIES.md). See [`LICENSE`](LICENSE) for the full ELv2 text.
