# Release Schedule

This schedule is committed to git for planned milestone tracking.

## Planned Releases

- `v1.1.0` - `2026-04-30` — consortium v2 **plus** inference_context v2, `recommended_action`, 5m velocity, simulation guardrails, SDK + OpenAPI parity, Case Detail explainability, **CI/security hygiene, five-minute eval path** (full detail: `docs/docs/releases/v1.1.0-2026-04-30.md`). **Finalization:** tag only after **full `ci.yml` + `security-scan.yml`** green on the RC commit, **frontend** and **`investigation-agent`** (copilot) tests passing, and **no P0** demo/stack blockers (see **§ Release candidate finalization & May handoff policy** in that release note). Changes after the tag default to **May 2026 Friday ships** → `v1.2.0`.
- `v1.2.0` - `2026-05-30` — strategic concentration: productized quality, device/session/integrity, location & co-presence, counters/velocity platform, analyst workflows, network/consortium, operations & lock-in inverse (see `docs/docs/releases/v1.2.0-2026-05-30.md`).
- `v1.3.0` - `2026-06-29`

## Publication Notes

- Future release notes are tracked under `docs/docs/releases/`.
- At each planned date, publish the release tag and GitHub release from the current validated commit for that milestone.
- If release scope shifts, update this file and corresponding release note files in git before publishing.

## v1.1.0 — tests, CI/CD, security, onboarding (mirrors release note)

Same bullets as [v1.1.0-2026-04-30.md](docs/docs/releases/v1.1.0-2026-04-30.md) § Tests / CI / validation.

### Tests and validation

- Unit coverage for **`inference_build`** (tiering, velocity, travel/colocation, **`derive_recommended_action`**).
- **`pytest`** for **`/v1/replay`** paired **`trace_ids`** mode (order, **`missing_trace_ids`**, empty-window 404).

### CI/CD, security hygiene, and first-run polish (ships with v1.1.0 train)

- **GitHub Actions CI** (`main` / `master`): Ruff; **decision-api** tests with coverage gate (**≥45%**, path to 60%+); **case-api**, **Python SDK**; **graph-service**; **integration-ingress**; **investigation-agent**; **graphql-gateway**, **event-ingest**, **analytics-sink**, **feature-service**, **ml-scoring**; **frontend** + **TypeScript SDK** **`npm run build`**; **Alembic** on PostgreSQL for decision/case APIs; **GraphQL** **`/metrics`**; coverage XML artifacts; **Docker builds** gated on all jobs.
- **Security scanning workflow**: **Trivy** filesystem + **decision-api** image → **SARIF** upload (where code scanning is enabled); weekly schedule.
- **Dependabot**: grouped updates for **GitHub Actions**, **pip** (core services), **npm** (frontend).
- **Docs:** **`SECURITY.md`** (responsible disclosure), **`LICENSE-DEPENDENCIES.md`** (Neo4j AGPL / lite and alternates), **`CODE_OF_CONDUCT.md`**, **`docs/docs/guides/security-scanning.md`**, **`docs/docs/guides/sandbox-five-minute.md`** (copy-paste evaluate + OSINT + UI path).
- **Onboarding:** **`.devcontainer/devcontainer.json`** (Codespaces / Docker-outside-Docker); **README** badges (CI, security scan, Codespaces); **walkthrough video** placeholder for maintainer Loom link on **[Tarka `README.md`](README.md)** ([github.com/pamu512/tarka](https://github.com/pamu512/tarka)), not Skuld or other repos.
- **`deploy/docker-compose.lite.yml`**: adds **integration-ingress** (**8003**) so lite stack matches the five-minute OSINT demo without full Neo4j.

### Planned validation (release gate)

- **`pytest`** (decision-api), frontend **`npm run build`**, and **TypeScript SDK** **`npm run build`** green before tag.
- **CI workflow green** on default branch: lint, all Python service test jobs, Node builds, Docker build matrix.
- **Trivy** security workflow completes (SARIF upload may depend on org plan); **Dependabot** enabled for the repository.
- **Lite compose** smoke: `docker compose -f deploy/docker-compose.lite.yml up -d --build` → **8000** evaluate, **8003** OSINT health, **3000** frontend reachable.
