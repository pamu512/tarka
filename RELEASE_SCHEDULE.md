# Release Schedule

This schedule is committed to git for planned milestone tracking.

## Planned Releases

- `v1.1.0` - `2026-04-30` — consortium v2 **plus** inference_context v2, `recommended_action`, 5m velocity, simulation guardrails, SDK + OpenAPI parity, Case Detail explainability, **CI/security hygiene, five-minute eval path** (full detail: `docs/docs/releases/v1.1.0-2026-04-30.md`). This train is still an **early-development beta**: evidence gates remain required, and any waiver must be explicit, scoped, and time-bound. **Finalization:** tag only after **full `ci.yml` + `security-scan.yml` + `secret-scan.yml`** green on the RC commit (or approved beta waiver documented in the release note), **frontend** and `**investigation-agent`** (copilot) tests passing, and **no P0** demo/stack blockers (see **§ Release candidate finalization & May handoff policy** in that release note). Changes after the tag default to **May 2026 Friday ships** → `v1.2.0`.
- `v1.2.0` - `2026-05-30` — strategic concentration: productized quality, device/session/integrity, location & co-presence, counters/velocity platform, analyst workflows, network/consortium, operations & lock-in inverse (see `docs/docs/releases/v1.2.0-2026-05-30.md`).
- `v1.3.0` - `2026-06-29`

## Early `v1.1.0` release note (review before push)

`v1.1.0` is an **early-development beta** release that stabilizes Tarka's core decision stack and makes the platform easier to evaluate and operate end-to-end.

- Decision quality: stronger `inference_context` + `recommended_action` contract and clearer analyst explainability surfaces.
- Platform reliability: hardened CI/security evidence path, explicit release gates, and improved smoke-test repeatability.
- Integration readiness: API/SDK/OpenAPI parity and a practical five-minute lite-stack workflow for faster onboarding.

This is a foundation release: it de-risks immediate adoption while preparing the system for broader v1.2/v1.3 productization.

## v1.1.0 pending tasks snapshot

Source of truth remains `docs/docs/releases/v1.1.0-2026-04-30.md` under **Pending tasks before tagging `v1.1.0`**.

- Run full `ci.yml` on final RC SHA in `main`/`master` workflow scope (`master` SHA `df3224c3b3e5056d03554ca9732fde2f25086139`, [run 24377895049](https://github.com/pamu512/tarka/actions/runs/24377895049)).
- Attach RC-linked `benchmark-latency-evaluate` artifact evidence (local artifact: `benchmark-latency-evaluate-local.txt`).
- Attach RC-linked `security-scan.yml` run evidence ([run 24377895059](https://github.com/pamu512/tarka/actions/runs/24377895059)).
- Attach RC-linked `secret-scan.yml` run evidence (beta-only temporary waiver: no `master` runs available yet via Actions API as of `2026-04-19`; expires within one week post-tag or on first successful `main/master` run).
- Re-run `scripts/ci/verify_release_candidate.sh` on final tag candidate and refresh evidence dates/SHA (passed on `release/v1.2.0` SHA `ec89ac96e47d47b56e9df0cf6e7e382d4bbea6ee`).
- Reconfirm no P0 blockers on the documented demo path before tag (GitHub issue search for open `P0` = `0`; smoke checks passed on `8000`/`8003`/`3000`).

## Recent commits and stack impact

- `860aeb2` (`feat(epic-c)`): adds `distinct_session_id_24h` in velocity manifest, improving counter parity and replay/rule consistency.
- `5d9f435` (`fix(ci)`): fixes decision-api Ruff and aggregate gate failures, improving release reliability.
- `663b104` (`merge`): combines location coherence and v1.1 prep work, improving cross-layer consistency (API + SDK + docs).
- `6cfcf74` (`chore(ci)`): introduces secret-scan and benchmark gate prep, improving evidence and governance discipline.
- `573b2c1` (`fix(location)`): tightens IP-geo gating and signal parsing, reducing noisy enrichment and improving trust in geo signals.
- `84d4a8d` and `3499264` (`feat(location)`): calibration status endpoint plus SDK/graph geo signals, improving model observability and explainability.
- `a91b3e4` (`feat(v1.2)`): vertical benchmark harness and ingress scorecards, advancing productization and operational monitoring.
- `ed6dc64` (`feat`): copilot and collaboration bridge readiness, improving analyst workflow responsiveness.

## Expected outcomes in coming releases

### `v1.2.0` (May 30, 2026)

- Vertical starter packs with deterministic benchmark scorecards and clearer promotion paths.
- Stronger counters/velocity and location coherence across online scoring, replay, and operator tooling.
- Better analyst + operator workflow depth via reliability scorecards and documented deployment options.

### `v1.3.0` (June 29, 2026)

- Trust Center, signed artifacts, and release-governance controls for enterprise posture.
- Evidence exports and audit-ready lineage for compliance and procurement workflows.
- Hardened operational readiness surfaces without breaking existing integration contracts.

## Publication Notes

- Future release notes are tracked under `docs/docs/releases/`.
- At each planned date, publish the release tag and GitHub release from the current validated commit for that milestone.
- If release scope shifts, update this file and corresponding release note files in git before publishing.

## Release numbering: ship `v1.1.0` vs skip to `v1.2.0`

**Keeping `v1.1.0` (recommended default):**

- **Pros:** Preserves a dated milestone for **inference v2**, **consortium v2**, **simulation guardrails**, **CI/security/onboarding** evidence, and **five-minute** onboarding—useful for users and auditors who already expect that tag. Smaller narrative jump; patch and hotfix semantics stay clear.
- **Cons:** Extra release overhead (notes, tag, comms) if `master` has already absorbed most of that scope and the team prefers fewer numbered drops.

**Skipping straight to `v1.2.0` (rename / fold trains):**

- **Pros:** One tag if `**v1.1.0` acceptance criteria are already met on `master`** and remaining work is clearly **Day 60** (vertical packs, ingress scorecards, fuller counter parity, benchmark story). Avoids marketing two adjacent “foundation” releases.
- **Cons:** Loses a distinct `**v1.1.0`** anchor in history (links, tickets, and checklists that name `v1.1.0` need a pointer to “folded into v1.2.0”); risk of **scope creep** if `v1.2.0` is used to bundle unfinished `v1.1.0` gates. Anything already published as `v1.1.0` cannot be silently redefined—update `**RELEASE_SCHEDULE.md`** and the relevant `**docs/docs/releases/*.md`** with an explicit **superseded-by** note.

**Practical rule:** If `**v1.1.0` is not tagged yet**, you may **fold** its checklist into `**v1.2.0`** only after every `**v1.1.0`** row you care about is green (or waived in writing). If `**v1.1.0` is already tagged**, ship incremental work as `**v1.2.0`** (or patches) rather than reusing the number.

## v1.1.0 — tests, CI/CD, security, onboarding (mirrors release note)

Same bullets as [v1.1.0-2026-04-30.md](docs/docs/releases/v1.1.0-2026-04-30.md) § Tests / CI / validation.

### Tests and validation

- Unit coverage for `**inference_build`** (tiering, velocity, travel/colocation, `**derive_recommended_action**`).
- `**pytest**` for `**/v1/replay**` paired `**trace_ids**` mode (order, `**missing_trace_ids**`, empty-window 404).

### CI/CD, security hygiene, and first-run polish (ships with v1.1.0 train)

- **GitHub Actions CI** (`main` / `master`): Ruff; **decision-api** tests with coverage gate (**≥48%** per `**.github/workflows/ci.yml`**, path to 60%+); case-api, Python SDK; graph-service; integration-ingress; investigation-agent; graphql-gateway, event-ingest, analytics-sink, feature-service, ml-scoring; frontend + TypeScript SDK `**npm run build`**; **Alembic** on PostgreSQL for decision/case APIs; **GraphQL** `**/metrics`**; `**benchmark-latency-evaluate`** artifact; coverage XML artifacts; **Docker builds** gated on all jobs.
- **Security scanning workflow**: **Trivy** filesystem + **decision-api** image → **SARIF** upload (where code scanning is enabled); weekly schedule.
- **Secret scanning workflow**: **TruffleHog** (`**.github/workflows/secret-scan.yml`**).
- **Dependabot**: grouped updates for **GitHub Actions**, **pip** (core services), **npm** (frontend).
- **Docs:** `**SECURITY.md`** (responsible disclosure), `**LICENSE-DEPENDENCIES.md`** (Neo4j AGPL / lite and alternates), `**CODE_OF_CONDUCT.md**`, `**docs/docs/guides/security-scanning.md**`, `**docs/docs/guides/sandbox-five-minute.md**` (copy-paste evaluate + OSINT + UI path).
- **Onboarding:** `**.devcontainer/devcontainer.json`** (Codespaces / Docker-outside-Docker); **README** badges (CI, security scan, Codespaces); **maintainer Loom walkthrough** on **[Tarka `README.md](README.md)`** — [five-minute sandbox + Case Detail](https://www.loom.com/share/b46f1eccbc6b438381ee44c6978f2f5e) ([github.com/pamu512/tarka](https://github.com/pamu512/tarka)), not Skuld or other repos.
- `**deploy/docker-compose.lite.yml**`: adds **integration-ingress** (**8003**) so lite stack matches the five-minute OSINT demo without full Neo4j.

### Planned validation (release gate)

- `**pytest`** (decision-api), frontend `**npm run build`**, and **TypeScript SDK** `**npm run build`** green before tag.
- **CI workflow green** on default branch: lint, all Python service test jobs, Node builds, Docker build matrix.
- **Trivy** security workflow completes (SARIF upload may depend on org plan); **Dependabot** enabled for the repository.
- **Lite compose** smoke: `docker compose -f deploy/docker-compose.lite.yml up -d --build` → **8000** evaluate, **8003** OSINT health, **3000** frontend reachable.