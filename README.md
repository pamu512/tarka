

# Tarka

[CI](https://github.com/pamu512/tarka/actions/workflows/ci.yml)
[Security scan](https://github.com/pamu512/tarka/actions/workflows/security-scan.yml)
[Secret scan](https://github.com/pamu512/tarka/actions/workflows/secret-scan.yml)
[Open in GitHub Codespaces](https://github.com/codespaces/new?hide_repo_select=true&ref=master&repo=pamu512%2Ftarka)

> **Prove every signal.**

Open-source, modular fraud detection platform. Pick the components you need or run the full stack.

*Tarka* — from Sanskrit तर्क (tarka), the method of logical hypothesis testing in Nyaya Shastra (Indian analytical philosophy). Every signal is a hypothesis; every decision is proved.

**Canonical repo:** [github.com/pamu512/tarka](https://github.com/pamu512/tarka)

**Saarthi (Investigation Copilot)** — **OSS** ships in this repo as `**services/investigation-agent`**. **Standalone paid:** [Saarthi Pro](https://github.com/pamu512/Saarthi-pro). **Buyer / PMO summary:** [Saarthi Pro vs OSS](docs/docs/guides/saarthi-pro-vs-oss.md).


|              | **OSS (`investigation-agent`)**        | **Saarthi Pro**                                                          |
| ------------ | -------------------------------------- | ------------------------------------------------------------------------ |
| **Best for** | Full Tarka stack, self-hosted ops      | Procurement, SLAs, governance roadmap, focused copilot SKU               |
| **You own**  | Upgrades, uptime, compliance mapping   | Commercial terms + vendor support (where purchased)                      |
| **Code**     | Here in `services/investigation-agent` | [github.com/pamu512/Saarthi-pro](https://github.com/pamu512/Saarthi-pro) |


## Deployment Reality

- **Production team:** plan for **2-3 engineers** to operate Tarka reliably.
- **Time to production:** expect **3-6 months** for a full production deployment.
- **Best fit scale:** strongest value in the **1M-10M transactions/year** range.
- **Typical TCO at 10M tx/year:** **$150K-$250K/year** all-in (infra + engineering operations).
- **Dual mode:** keep full-stack Tarka for advanced operations; use **Tarka Lite** for simpler, reliable deployments.

## What’s on trunk (shipping now)

These capabilities are in the codebase today and roll forward on `master`:

- **Decision API:** normalized `**inference_context`** on evaluate responses (integrity, tamper, network trust, replay, geo-consistency, top signals) plus OpenAPI contract alignment; **session geo** merges optional **browser GPS** and **server IP geo** hints; `**sdk:geo_ip_mismatch`** / `**sdk:geo_tz_mismatch**` signal tags when inconsistent; `**/v1/ops/calibration-status**` and `**calibration_status**` on `**/v1/ops/governance**` for drift posture (when an external **calibration service** is not configured, governance still returns a **hint** such as `calibration_service_not_configured`—see `CALIBRATION_SERVICE_URL` in [deployment](docs/docs/guides/deployment.md)).
- **Ingress hardening:** **replay-style payload detection** (short-lived Redis signatures) folded into scoring and audit context; optional **HMAC** on `POST /v1/decisions/evaluate` when `**REQUEST_SIGNATURE_SECRET`** is set (see [TLS pinning & signed requests](docs/docs/guides/tls-pinning-and-signed-requests.md)).
- **SDKs:** **Python** and **TypeScript** clients typed for `inference_context` on evaluate responses; **TypeScript** optional `**enableGeo`** (browser GPS); **Python** server collector optional `**enable_ip_geo`** / `**ENABLE_IP_GEO_LOOKUP**` (public IP lookup is **off** by default).
- **Graph (lite path):** default schema includes `**Place`** (quantized geo cells) and `**SEEN_AT**` edges for co-location–style graph context when enabled.
- **Frontend:** case explainability surfaces **inference metrics**; API client can **fall back to mock data** when backends are down (demo-friendly).
- **Ops / planning:** module **project roadmaps** under `docs/docs/projects/`, **30/60/90** plan, competitive notes, and **OSS adoption backlog** (issues + dependency order in docs).

### April 2026 — Investigation copilot, collaboration ingress, and ops

- **Investigation agent (Saarthi):** `**GET /v1/ready`** (data-dir readiness), `**GET /v1/setup**` (first-run checklist), and a `**production**` object on `**GET /v1/health**` when production profiling is enabled; `**GET /v1/workflows**` with `**workflow_id` / `workflow_params**` (plus `**playbook_id` / `batch_id**` where applicable) on `**POST /v1/chat**`; **case-summary PDF** and **turn-bundle** report routes; optional **copilot rate limits** and **request body size cap**. Reference env: `**services/investigation-agent/.env.example`**. Hardening compose: `**deploy/docker-compose.production-hardening.yml**`. Integration notes: **[CHANGELOG_INTEGRATION](docs/docs/guides/CHANGELOG_INTEGRATION.md)**.
- **Trust / ops, evidence summary, parity:** Decision API `**GET /v1/ops/evaluation-posture`** + `**GET /v1/slo**` for the console readiness strip; `**POST /v1/evidence/summary**` (deterministic citations + next actions); Feature Service `**POST /v1/internal/parity/verify**`. Indexed in **[API Reference](docs/docs/api-reference.md)** (Decision, Feature Service, Investigation Agent sections).
- **Collaboration chat (Slack, Teams, Lark):** implemented **inside** `**services/investigation-agent`** as `**investigation_agent.chat_bridge**` (mounted on the agent process; the stand-alone `**services/collaboration-chat-bridge**` service was **removed** in favor of this consolidation). Features include optional **per-source minute rate limits**, **Slack file** text extraction (plain text, CSV, PDF, **Excel .xlsx**), **SSRF-hardened** fetch of the first public `**https://`** URL, directives `**!wf**`, `**!wfp**`, `**!style**`, and forwarding workflow/batch fields to the copilot. Operator wiring: **[Collaboration chat & cloud](docs/docs/guides/investigation-collaboration-chat-aws-azure.md)** (replace references to a separate `collaboration-chat-bridge` container with `**investigation-agent`** on **:8006**).
- **Frontend:** **Investigation** page updates for copilot setup and workflows (`frontend/src/pages/Investigation.tsx`).
- **Observability & deploy:** Grafana dashboard JSON for copilot metrics under `**deploy/observability/`**; optional `**deploy/docker-compose.host-ports.override.yml**` for local port mapping; guide **[Investigation CMS & ITSM](docs/docs/guides/investigation-cms-and-itsm-integrations.md)**.

### v1.1.0 train — tests, CI/CD, security, onboarding

Mirrors [docs/docs/releases/v1.1.0-2026-04-30.md](docs/docs/releases/v1.1.0-2026-04-30.md) and [RELEASE_SCHEDULE.md](RELEASE_SCHEDULE.md).

**Tests and validation**

- Unit coverage for `**inference_build`** (tiering, velocity, travel/colocation, `**derive_recommended_action**`).
- `**pytest**` for `**/v1/replay**` paired `**trace_ids**` mode (order, `**missing_trace_ids**`, empty-window 404).

**CI/CD, security hygiene, and first-run polish**

- **GitHub Actions CI** (`main` / `master`): Ruff; **decision-api** tests with coverage gate (**≥48%** as enforced in `**.github/workflows/ci.yml`**, path to 60%+); **case-api**, **Python SDK**; **graph-service**; **integration-ingress**; **investigation-agent**; **graphql-gateway**, **event-ingest**, **analytics-sink**, **feature-service**, **ml-scoring**; **frontend** `**npm run test`** then `**npm run build**` + **TypeScript SDK** `**npm run build`**; **Alembic** migrations for decision/case APIs on PostgreSQL startup; **GraphQL** `**/metrics`** via shared observability; `**benchmark-latency-evaluate**` job (lite compose + `**scripts/benchmarks/latency_evaluate.py**` artifact); coverage XML artifacts; **Docker builds** gated on all jobs.
- **Security scanning workflow**: **Trivy** filesystem + **decision-api** image → **SARIF** upload (where code scanning is enabled); weekly schedule.
- **Secret scanning workflow**: **TruffleHog** on push/PR/schedule (`**.github/workflows/secret-scan.yml`**).
- **Dependabot**: grouped updates for **GitHub Actions**, **pip** (core services), **npm** (frontend).
- **Docs:** `**SECURITY.md`** (responsible disclosure), `**LICENSE-DEPENDENCIES.md**` (Neo4j AGPL / lite and alternates), `**CODE_OF_CONDUCT.md**`, `**docs/docs/guides/security-scanning.md**`, `**docs/docs/guides/sandbox-five-minute.md**` (copy-paste evaluate + OSINT + UI path).
- **Onboarding:** `**.devcontainer/devcontainer.json`** (Codespaces / Docker-outside-Docker); **README** badges (CI, security scan, Codespaces); **Maintainer walkthrough (Loom, [Tarka](https://github.com/pamu512/tarka) / this repo only):** [five-minute sandbox + Case Detail explainability](https://www.loom.com/share/b46f1eccbc6b438381ee44c6978f2f5e). *(Not [Skuld](https://github.com/pamu512/Skuld) or other repos — those are separate products.)*
- `**deploy/docker-compose.lite.yml`**: adds **integration-ingress** (**8003**) so lite stack matches the five-minute OSINT demo without full Neo4j. Optional `**--profile ingest`** adds **NATS** + **event-ingest** (**8007**) for the **evaluate + case + async ingest** demo (see [Demo vertical smoke](scripts/README.md#demo-vertical-smoke)).

**Planned validation (release gate)**

- `**pytest`** (decision-api), frontend `**npm run test**` + `**npm run build**`, and **TypeScript SDK** `**npm run build`** green before tag.
- **CI workflow green** on default branch: lint, all Python service test jobs, Node builds, Docker build matrix.
- **Trivy** security workflow completes (SARIF upload may depend on org plan); **Dependabot** enabled for the repository.
- **Lite compose** smoke: `docker compose -f deploy/docker-compose.lite.yml up -d --build` → **8000** evaluate, **8003** OSINT health, **3000** frontend reachable.

## Client SDKs (evaluate vs ingest)

- **Synchronous scoring:** call **Decision API** `POST /v1/decisions/evaluate` via `**DecisionClient`** (Python / TypeScript under `packages/`).
- **Async high-volume path:** send events to **event-ingest** `POST /v1/events` (NATS → worker → evaluate) via `**EventIngestClient`**; optional `**Idempotency-Key**` when `**REDIS_URL**` is configured on ingest.

Onboarding (ports, metrics, replay script): **[docs/docs/guides/ingest-replay-onboarding.md](docs/docs/guides/ingest-replay-onboarding.md)** — see also **[docs/docs/sdks/python.md](docs/docs/sdks/python.md)** and **[docs/docs/sdks/typescript.md](docs/docs/sdks/typescript.md)**.

## Examples, benchmarks, and ops


| What                                                                         | Where                                                                                            |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| **Scripts index** (CI gates, policy/ML validators, links to subtree READMEs) | [scripts/README.md](scripts/README.md)                                                           |
| **Three walkthroughs** (payments + ML, bot defense, IOC + graph)             | [docs/docs/guides/examples/README.md](docs/docs/guides/examples/README.md)                       |
| **Evaluate latency** (stdlib script)                                         | [scripts/benchmarks/README.md](scripts/benchmarks/README.md)                                     |
| **Simulation / A-B rules**                                                   | [docs/docs/guides/shadow-and-ab-testing.md](docs/docs/guides/shadow-and-ab-testing.md)           |
| **Prometheus + Grafana** (compose add-on)                                    | [deploy/observability/README.md](deploy/observability/README.md)                                 |
| **Apache-friendly graph options** (vs Neo4j AGPL)                            | [docs/docs/guides/graph-backend-alternatives.md](docs/docs/guides/graph-backend-alternatives.md) |


## Shipping cadence & releases


| Artifact                                          | Where                                                                                                                                              |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Version targets (`v1.1.0` … `v1.3.0`)             | [RELEASE_SCHEDULE.md](RELEASE_SCHEDULE.md)                                                                                                         |
| May 2026 Friday train (weekly commits / themes)   | [docs/docs/guides/release-calendar-2026-05.md](docs/docs/guides/release-calendar-2026-05.md) — queue: `scripts/release/release-queue-2026-05.json` |
| OSS-pattern execution order (`#31`–`#54` + graph) | [docs/docs/guides/oss-ship-order-dependencies.md](docs/docs/guides/oss-ship-order-dependencies.md)                                                 |
| Product milestones (Epics A–F)                    | [docs/docs/guides/roadmap-30-60-90.md](docs/docs/guides/roadmap-30-60-90.md)                                                                       |


**June 2026** milestones on GitHub group the **borrowed-from-OSS** workstream (policy DAG, typologies, parity gates, deployment profiles, scorecards, etc.) — see issues labeled `borrowed-from-OSS` and the [module swimlanes project](https://github.com/users/pamu512/projects/3).

## Who Should Choose Tarka

Choose Tarka if you need fraud controls that your team can own, audit, and evolve quickly.

- **Fintech, payments, lending, crypto, and marketplaces** that need real-time decisions plus investigations.
- **Risk and fraud teams** that want rules + ML + graph in one stack, with explainable decisions and evidence exports.
- **Engineering teams** that prefer open, modular architecture over closed vendor lock-in.
- **Compliance-heavy organizations** that need auditable controls, traceability, and regional privacy support.
- **Teams with existing tools** that want to integrate KYC, sanctions, device, CRM, or dispute providers via one hub.

Tarka may be less ideal if you only need a very basic, single-rule workflow and do not require integrations, investigations, or governance.

## Install

```bash
# Clone the repository
git clone https://github.com/pamu512/tarka.git
cd tarka

# Option 1: Interactive installer (pick modules)
python tarka.py install

# Option 2: Install everything
python tarka.py install --all

# Option 3: Minimal setup (5-minute quickstart — Decision + Case + OSINT ingress + UI; no Neo4j)
python tarka.py install --lite

# Option 4: Specific modules only
python tarka.py install --modules core,graph,ml,frontend
```

## Try in five minutes (Decision API + inference + OSINT + UI)

**Full copy-paste path:** [docs/docs/guides/sandbox-five-minute.md](docs/docs/guides/sandbox-five-minute.md) — `docker compose -f deploy/docker-compose.lite.yml up -d --build`, then `curl` the Decision API for live `**inference_context`**, Integration Ingress for **parallel OSINT**, and open the **frontend** (mock fallbacks for graph-heavy views when Neo4j is not running).

**Demo vertical (synchronous evaluate → case API → event ingest, optional UI):** start **Lite** with the `**ingest`** profile and the optional key override, then run the smoke script (CI contracts in `scripts/ci/test_demo_vertical_contracts.py`):

```bash
docker compose -f deploy/docker-compose.lite.yml -f deploy/docker-compose.demo-vertical.yml --profile ingest up -d --build
export DEMO_API_KEY=tarka-demo-vertical
python3 scripts/ci/demo_vertical_smoke.py
```

Omit `docker-compose.demo-vertical.yml` if you prefer the default auth model; the smoke script falls back to a **read-only** case list when case **create** returns **401/403**. Use `**--skip-frontend`** if port **3000** is not available.

### Prebuilt images (optional)

```bash
docker compose -f https://raw.githubusercontent.com/pamu512/tarka/master/deploy/docker-compose.sandbox.yml up -d
```

- `http://localhost:3000` — frontend  
- `http://localhost:8000/decisions/v1/health` — decision plane (via **core-api**)  
- `http://localhost:8003/v1/health` — integration-ingress

### GitHub Codespaces

Use the badge at the top of this README, then in the terminal:  
`docker compose -f deploy/docker-compose.lite.yml up -d --build`  
(Ports **3000**, **8000**, **8003**, **8004**, **8006**, **8010** are forwarded from `.devcontainer/devcontainer.json`.)

## Walkthrough video

Experience Tarka -**[Click Here](https://www.loom.com/share/b46f1eccbc6b438381ee44c6978f2f5e).**

## Security & compliance (table stakes)

- **[SECURITY.md](SECURITY.md)** — responsible disclosure  
- **[LICENSE-DEPENDENCIES.md](LICENSE-DEPENDENCIES.md)** — Neo4j AGPL and Apache-friendly **lite** option  
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)**  
- **Dependabot** + **Trivy** workflows — see [docs/docs/guides/security-scanning.md](docs/docs/guides/security-scanning.md)
- **Regional AI governance builds** (US / EU+UK / global Investigation Copilot profiles) — [docs/docs/guides/ai-governance-regional-builds.md](docs/docs/guides/ai-governance-regional-builds.md) · [deploy/profiles/ai-governance/README.md](deploy/profiles/ai-governance/README.md)

### Requirements

- Python 3.11+
- Docker & Docker Compose

### What Each Module Includes

CLI slugs stay stable; **codenames** are the product story (see [Module codenames](docs/docs/guides/module-codenames.md)). **Riti** (`gateway`) draws on **rīti** (रीति) in the technical Sanskrit lexicon—often read in sources such as the *Viṣṇudharmottarapurāṇa* as **iron rust**, an ingredient of **Vajralepa** (a hard cement)—as a metaphor for the GraphQL layer that **binds** services into one API surface.


| Slug          | Codename    | What You Get                                                                                                                                                | Infrastructure                          |
| ------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| `core`        | **Hetu**    | Decision API, rules engine, Redis tags/scores, OPA                                                                                                          | Postgres, Redis                         |
| `graph`       | **Jaala**   | Neo4j entity graph, community detection, fraud rings                                                                                                        | Neo4j                                   |
| `ml`          | **Anumana** | ONNX inference, adaptive autoencoder, feature engineering                                                                                                   | —                                       |
| `cases`       | **Lekh**    | Case management, workflow automation, SAR generation                                                                                                        | Postgres                                |
| `integration` | **Setu**    | KYC adapters, **12-source OSINT enrichment**                                                                                                                | Postgres                                |
| `agent`       | **Saarthi** | AI investigation copilot (LLM tool-use)                                                                                                                     | —                                       |
| `streaming`   | **Srotas**  | High-throughput event ingestion via NATS JetStream                                                                                                          | NATS                                    |
| `analytics`   | **Kala**    | Historical decision analytics (**full** stack: ClickHouse + NATS; **Tarka Lite**: Postgres-backed **data-platform** — see `deploy/docker-compose.lite.yml`) | ClickHouse + NATS *or* Postgres + Redis |
| `gateway`     | **Riti**    | Unified GraphQL API over all REST services                                                                                                                  | —                                       |
| `frontend`    | **Dwar**    | React dashboard (10 pages)                                                                                                                                  | —                                       |


### pip Install (Library Use)

```bash
# Install as Python library with specific extras
pip install tarka[core]              # Just decision engine deps
pip install tarka[core,graph,ml]     # Core + graph + ML
pip install tarka[full]              # Everything
pip install tarka[lite]              # Core + cases
pip install tarka[standard]          # Core + graph + ML + cases + OSINT
```

## Managing Services

```bash
python tarka.py start              # Start all installed modules
python tarka.py stop               # Stop all services
python tarka.py status             # Show running services & health
python tarka.py logs -f            # Follow all logs
python tarka.py logs decision-api  # Logs for one service

# Add or remove modules later
python tarka.py add graph,ml       # Add graph and ML to existing install
python tarka.py remove analytics   # Remove analytics module

# Local development (no Docker)
python tarka.py dev decision-api   # Run decision-api with hot-reload

# List all available modules
python tarka.py list

# Show module details
python tarka.py info graph

# Clean uninstall
python tarka.py uninstall

# Optional local forensic suite (Shadow — submodule tools/shadow)
python tarka.py forensics              # Tauri desktop when Rust is installed, else web+API
python tarka.py forensics --web        # Browser + FastAPI only
python tarka.py forensics --init-only  # Clone submodule, .env, deps; do not launch
```

See **[Local forensic suite (Shadow)](docs/docs/guides/local-forensics-suite.md)** for prerequisites, Postgres wiring, and data boundaries.

## Architecture

```
SDK (Web/Android/iOS/Python) --> Core API :8000 (/decisions, /cases) --> Redis (tags + scores)
                                     |
                   +-----------------+-----------------+
                   |                 |                 |
              Rule Engine       Signal API :8004   OPA (optional)
              (no-code UI)    (/features, /ml, …)
              (shadow mode)   (ONNX + adaptive)
              (AI recommend)  (drift detection)
              (explainability)
                   |
              OSINT Enrichment
              (Shodan, AbuseIPDB, GreyNoise,
               EmailRep, HIBP, IPinfo, RDAP)
                   |
              Graph Service --> Neo4j
              (community detection, fraud rings,
               risk propagation)

Investigation UI --> Core API (/cases) --> Graph Service
                       |
                  AI Agent (LLM tool-use)

Data plane :8007 --> NATS JetStream --> ClickHouse *(streaming + analytics profiles)*
```

## Components


| Service               | Port | Description                                                                                                                         |
| --------------------- | ---- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `core-api`            | 8000 | **Macroservice:** decision + case apps (`/decisions`, `/cases`); scoring, audit, workflows, SAR/STR                                 |
| `graph-service`       | 8001 | Entity graph (Neo4j), GDS algorithms, tag storage on nodes                                                                          |
| `integration-ingress` | 8003 | KYC webhooks, adapter registry, **OSINT enrichment (12 sources)**                                                                   |
| `signal-api`          | 8004 | **Macroservice:** features, ML, calibration, counters, location (`/features`, `/ml`, …)                                            |
| `investigation-agent` | 8006 | AI copilot with LLM tool-use loop **and embedded Slack/Teams/Lark chat bridge** (`chat_bridge`, former stand-alone service removed) |
| `data-plane`          | 8007 | **Macroservice:** event ingest + analytics sink (same port; NATS + optional ClickHouse)                                            |
| `graphql-gateway`     | 8010 | Unified GraphQL API (defaults target **core-api** mounts)                                                                         |
| `frontend`            | 3000 | React dashboard (10 pages)                                                                                                          |
| **Shadow (add-on)**   | 8742 (API) | Local forensic console — **Git submodule** [`tools/shadow`](tools/shadow); `python tarka.py forensics`; not in default Compose |

Source modules under `services/decision-api`, `services/case-api`, `services/feature-service`, `services/ml-scoring`, etc. still power **core-api** / **signal-api**; CI and `tarka.py dev` can target either the macroservice or a single module.

**Cross-service env alignment:** **core-api** sets in-process `DECISION_API_URL` for the case app; `investigation-agent` uses `CASE_API_URL` / `DECISION_API_URL` pointing at **`http://core-api:8000/{cases|decisions}`**, plus optional `GRAPH_SERVICE_URL` / `UPSTREAM_API_KEY`. See [docs/docs/guides/deployment.md](docs/docs/guides/deployment.md), [service-ports.md](docs/docs/guides/service-ports.md), and `deploy/.env.example`.


| SDK                             | Platform                                                                                                                 |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `packages/fraud-sdk-typescript` | Web (browser) — device signals + behavioral biometrics                                                                   |
| `packages/fraud-sdk-python`     | Server-side Python — IP/geo signal collection                                                                            |
| `packages/fraud-sdk-android`    | **Android (Kotlin)** — `io.tarka.sdk`, Play Integrity, `device_context` ([README](packages/fraud-sdk-android/README.md)) |
| `packages/fraud-sdk-ios`        | **iOS (Swift)** — App Attest, `device_context` ([README](packages/fraud-sdk-ios/README.md))                              |


**SDK positioning (directional, mid-scale scores):** [docs/docs/guides/sdk-scorecard-2026-01.md](docs/docs/guides/sdk-scorecard-2026-01.md).

**Highly regulated sectors (fintech, banking, crypto-adjacent):** optional **[regulated markets feature pack](docs/docs/guides/feature-pack-regulated-markets.md)** checklist — ingress integrity, attestation, audit, self-hosted boundaries. **SOC 2 / PCI / ISO** orientation: [compliance readiness](docs/docs/guides/compliance-readiness-soc2-pci-iso.md).

## Frontend Pages


| Page           | Description                                                                                                             |
| -------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Dashboard      | Real-time decision stats, hourly charts, top entities                                                                   |
| Cases          | Investigation case list with workflow status                                                                            |
| Rules          | **No-code visual rule builder** with drag-and-drop conditions, templates                                                |
| Shadow Mode    | Observation dashboard: toggle packs active/shadow/disabled, divergence metrics                                          |
| Simulation     | Synthetic fraud scenarios, A/B rule testing, precision/recall/F1 analysis                                               |
| Graph Explorer | Neo4j visualization, community detection, fraud ring discovery                                                          |
| OSINT          | **12-source enrichment** for email/phone/IP/domain with composite risk scoring                                          |
| Analytics      | ClickHouse-powered historical analytics                                                                                 |
| Investigation  | AI agent chat with tool-use for case research                                                                           |
| Case Detail    | Full case view with timeline, evidence, comments; **decision explainability** includes `inference_context` when present |


## OSINT Enrichment

Built-in OSINT enrichment queries 12 sources in parallel (9 work without API keys):


| Source            | Type     | Key Needed | Data                          |
| ----------------- | -------- | ---------- | ----------------------------- |
| Shodan InternetDB | IP       | No         | Open ports, CVEs, tags        |
| AbuseIPDB         | IP       | Optional   | Abuse confidence score        |
| GreyNoise         | IP       | Optional   | Scanner classification        |
| IPinfo Lite       | IP       | Optional   | Geo, ASN, VPN/proxy/Tor       |
| ip-api.com        | IP       | No         | Geo, ISP, proxy, hosting      |
| EmailRep.io       | Email    | Optional   | Reputation, social profiles   |
| Gravatar          | Email    | No         | Avatar existence              |
| Have I Been Pwned | Email    | No         | Breach count                  |
| DNS MX            | Email    | No         | Mail server validation        |
| NumVerify         | Phone    | Optional   | Carrier, line type            |
| RDAP              | Domain   | No         | Registration age, nameservers |
| GitHub            | Identity | No         | Profile discovery             |


Configure optional keys in `.env`:

```bash
ABUSEIPDB_KEY=your-key
GREYNOISE_KEY=your-key
EMAILREP_KEY=your-key
NUMVERIFY_KEY=your-key
IPINFO_TOKEN=your-token
```

## SDK Device Signals

All SDKs collect device signals and send them as `device_context` with each evaluation:

- **Emulator/simulator detection** (WebDriver, headless browser, Android emulator, iOS simulator)
- **VPN detection** (WebRTC leak, Android NET_CAPABILITY_NOT_VPN, iOS utun interfaces)
- **Bot detection** (behavioral entropy, automation framework detection, bot User-Agent)
- **Behavioral biometrics** (typing cadence, mouse dynamics, scroll patterns, session timing)
- **Location spoofing** (mock location providers, GPS consistency)
- **App repackaging** (certificate hash verification, Play Integrity, App Attest)
- **Security handshake** (server nonce → SDK signs with platform attestation → server verifies)

Signals become `sdk:*` tags on Redis and graph nodes (e.g., `sdk:emulator`, `sdk:vpn`, `sdk:bot`).

## Configuration

Decision API supports configurable scoring:

- `DENY_THRESHOLD` (default 80) — score at which to deny
- `REVIEW_THRESHOLD` (default 50) — score at which to flag for review
- `SCORE_BLEND_STRATEGY` — `average` (default), `max`, or `rules_only`

Set `API_KEYS=key1,key2` on any service to require `X-API-Key` header. Leave empty to disable (development mode).

## License

Application code in this repository is **Apache-2.0** unless otherwise noted. See [LICENSE](LICENSE).

**Third-party and copyleft components:** Neo4j (when used) is **AGPL-3.0** for the database in typical networked deployments. Use `**docker-compose.lite`** or review [LICENSE-DEPENDENCIES.md](LICENSE-DEPENDENCIES.md) before production architecture sign-off.