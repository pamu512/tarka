# Tarka

> **Prove every signal.**

Open-source, modular fraud detection platform. Pick the components you need or run the full stack.

*Tarka* — from Sanskrit तर्क (tarka), the method of logical hypothesis testing in Nyaya Shastra (Indian analytical philosophy). Every signal is a hypothesis; every decision is proved.

**Canonical repo:** [github.com/pamu512/tarka](https://github.com/pamu512/tarka)

## What’s on trunk (shipping now)

These capabilities are in the codebase today and roll forward on `master`:

- **Decision API:** normalized **`inference_context`** on evaluate responses (integrity, tamper, network trust, replay, geo-consistency, top signals) plus OpenAPI contract alignment.
- **Ingress hardening:** **replay-style payload detection** (short-lived Redis signatures) folded into scoring and audit context.
- **SDKs:** **Python** and **TypeScript** clients typed for `inference_context` on evaluate responses.
- **Frontend:** case explainability surfaces **inference metrics**; API client can **fall back to mock data** when backends are down (demo-friendly).
- **Ops / planning:** module **project roadmaps** under `docs/docs/projects/`, **30/60/90** plan, competitive notes, and **OSS adoption backlog** (issues + dependency order in docs).

## Shipping cadence & releases

| Artifact | Where |
|----------|--------|
| Version targets (`v1.1.0` … `v1.3.0`) | [RELEASE_SCHEDULE.md](RELEASE_SCHEDULE.md) |
| May 2026 Friday train (weekly commits / themes) | [docs/docs/guides/release-calendar-2026-05.md](docs/docs/guides/release-calendar-2026-05.md) — queue: `scripts/release/release-queue-2026-05.json` |
| OSS-pattern execution order (`#31`–`#54` + graph) | [docs/docs/guides/oss-ship-order-dependencies.md](docs/docs/guides/oss-ship-order-dependencies.md) |
| Product milestones (Epics A–F) | [docs/docs/guides/roadmap-30-60-90.md](docs/docs/guides/roadmap-30-60-90.md) |

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

# Option 3: Minimal setup (5-minute quickstart)
python tarka.py install --lite

# Option 4: Specific modules only
python tarka.py install --modules core,graph,ml,frontend
```

## Sandbox (No Full Clone)

Use this when you want a quick evaluator environment without cloning the full repository locally.

### Option A: Prebuilt Docker Sandbox

Run the published sandbox compose file directly:

```bash
docker compose -f https://raw.githubusercontent.com/pamu512/tarka/master/deploy/docker-compose.sandbox.yml up -d
```

Then open:

- `http://localhost:3000` (frontend)
- `http://localhost:8000/v1/health` (decision-api)
- `http://localhost:8003/v1/health` (integration-ingress)

Stop it:

```bash
docker compose -f https://raw.githubusercontent.com/pamu512/tarka/master/deploy/docker-compose.sandbox.yml down
```

### Option B: 1-click cloud dev sandbox

Open directly in Codespaces (no local clone required):

- [Open Tarka in Codespaces](https://github.com/codespaces/new?hide_repo_select=true&repo=pamu512/tarka)

### Requirements

- Python 3.11+
- Docker & Docker Compose

### What Each Module Includes

CLI slugs stay stable; **codenames** are the product story (see [Module codenames](docs/docs/guides/module-codenames.md)).

| Slug | Codename | What You Get | Infrastructure |
|------|----------|-------------|----------------|
| `core` | **Hetu** | Decision API, rules engine, Redis tags/scores, OPA | Postgres, Redis |
| `graph` | **Jaala** | Neo4j entity graph, community detection, fraud rings | Neo4j |
| `ml` | **Anumana** | ONNX inference, adaptive autoencoder, feature engineering | — |
| `cases` | **Nirnaya** | Case management, workflow automation, SAR generation | Postgres |
| `integration` | **Setu** | KYC adapters, **12-source OSINT enrichment** | Postgres |
| `agent` | **Saarthi** | AI investigation copilot (LLM tool-use) | — |
| `streaming` | **Srotas** | High-throughput event ingestion via NATS JetStream | NATS |
| `analytics` | **Itihasa** | ClickHouse OLAP, historical decision analytics | ClickHouse, NATS |
| `gateway` | **Dvara** | Unified GraphQL API over all REST services | — |
| `frontend` | **Sakshi** | React dashboard (10 pages) | — |

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
```

## Architecture

```
SDK (Web/Android/iOS/Python) --> Decision API --> Redis (tags + scores)
                                     |
                   +-----------------+-----------------+
                   |                 |                 |
              Rule Engine       ML Scoring        OPA (optional)
              (no-code UI)    (ONNX + adaptive)
              (shadow mode)   (drift detection)
              (AI recommend)  (explainability)
                   |
              OSINT Enrichment
              (Shodan, AbuseIPDB, GreyNoise,
               EmailRep, HIBP, IPinfo, RDAP)
                   |
              Graph Service --> Neo4j
              (community detection, fraud rings,
               risk propagation)

Investigation UI --> Case API --> Graph Service
                       |
                  AI Agent (LLM tool-use)

Event Ingest --> NATS JetStream --> Analytics Sink --> ClickHouse
```

## Components

| Service | Port | Description |
|---------|------|-------------|
| `decision-api` | 8000 | Fraud scoring, attestation, rule + ML orchestration, simulation, recommendations |
| `graph-service` | 8001 | Entity graph (Neo4j), GDS algorithms, tag storage on nodes |
| `case-api` | 8002 | Investigation cases, workflow automation, SAR/STR generation |
| `integration-ingress` | 8003 | KYC webhooks, adapter registry, **OSINT enrichment (12 sources)** |
| `feature-service` | 8004 | Feature engineering, enrichment, OSINT signal injection |
| `ml-scoring` | 8005 | ONNX inference, adaptive autoencoder, drift detection, model registry |
| `investigation-agent` | 8006 | AI copilot with LLM tool-use loop |
| `event-ingest` | 8007 | NATS-based high-throughput event ingestion |
| `analytics-sink` | 8008 | ClickHouse analytics writer |
| `graphql-gateway` | 8010 | Unified GraphQL API |
| `frontend` | 3000 | React dashboard (10 pages) |

| SDK | Platform |
|-----|----------|
| `packages/fraud-sdk-typescript` | Web (browser) — device signals + behavioral biometrics |
| `packages/fraud-sdk-python` | Server-side Python — IP/geo signal collection |
| `packages/fraud-sdk-android` | Android (Kotlin) — Play Integrity attestation |
| `packages/fraud-sdk-ios` | iOS (Swift) — App Attest |

## Frontend Pages

| Page | Description |
|------|-------------|
| Dashboard | Real-time decision stats, hourly charts, top entities |
| Cases | Investigation case list with workflow status |
| Rules | **No-code visual rule builder** with drag-and-drop conditions, templates |
| Shadow Mode | Observation dashboard: toggle packs active/shadow/disabled, divergence metrics |
| Simulation | Synthetic fraud scenarios, A/B rule testing, precision/recall/F1 analysis |
| Graph Explorer | Neo4j visualization, community detection, fraud ring discovery |
| OSINT | **12-source enrichment** for email/phone/IP/domain with composite risk scoring |
| Analytics | ClickHouse-powered historical analytics |
| Investigation | AI agent chat with tool-use for case research |
| Case Detail | Full case view with timeline, evidence, comments; **decision explainability** includes `inference_context` when present |

## OSINT Enrichment

Built-in OSINT enrichment queries 12 sources in parallel (9 work without API keys):

| Source | Type | Key Needed | Data |
|--------|------|-----------|------|
| Shodan InternetDB | IP | No | Open ports, CVEs, tags |
| AbuseIPDB | IP | Optional | Abuse confidence score |
| GreyNoise | IP | Optional | Scanner classification |
| IPinfo Lite | IP | Optional | Geo, ASN, VPN/proxy/Tor |
| ip-api.com | IP | No | Geo, ISP, proxy, hosting |
| EmailRep.io | Email | Optional | Reputation, social profiles |
| Gravatar | Email | No | Avatar existence |
| Have I Been Pwned | Email | No | Breach count |
| DNS MX | Email | No | Mail server validation |
| NumVerify | Phone | Optional | Carrier, line type |
| RDAP | Domain | No | Registration age, nameservers |
| GitHub | Identity | No | Profile discovery |

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

Apache-2.0. See [LICENSE](LICENSE).

Note: Neo4j Community Edition is GPLv3. The graph service abstraction supports alternative backends (JanusGraph/Gremlin).
