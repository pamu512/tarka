# Tarka

> **Prove every signal.**

Open-source, modular fraud detection platform. Pick the components you need or run the full stack.

*Tarka* — from Sanskrit तर्क (tarka), the method of logical hypothesis testing in Nyaya Shastra (Indian analytical philosophy). Every signal is a hypothesis; every decision is proved.

## Install

```bash
# Clone the repository
git clone https://github.com/tarka-fraud/tarka.git
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

### Requirements

- Python 3.11+
- Docker & Docker Compose

### What Each Module Includes

| Module | What You Get | Infrastructure |
|--------|-------------|----------------|
| `core` | Decision API, rules engine, Redis tags/scores, OPA | Postgres, Redis |
| `graph` | Neo4j entity graph, community detection, fraud rings | Neo4j |
| `ml` | ONNX inference, adaptive autoencoder, feature engineering | — |
| `cases` | Case management, workflow automation, SAR generation | Postgres |
| `integration` | KYC adapters, **12-source OSINT enrichment** | Postgres |
| `agent` | AI investigation copilot (LLM tool-use) | — |
| `streaming` | High-throughput event ingestion via NATS JetStream | NATS |
| `analytics` | ClickHouse OLAP, historical decision analytics | ClickHouse, NATS |
| `gateway` | Unified GraphQL API over all REST services | — |
| `frontend` | React dashboard (10 pages) | — |

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
| Case Detail | Full case view with timeline, evidence, comments |

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
