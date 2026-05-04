# Tarka: Audit-First Fraud Infrastructure

> **Prove every signal and the story behind it.**

Tarka — from Sanskrit तर्क (tarka), the method of logical hypothesis testing. **In Tarka, a fraud signal is a hypothesis. In our code, that hypothesis is only 'proven' once it is written to a durable audit log. If it isn't in the database, it didn't happen.**

Tarka is an open-source, modular fraud detection platform. Pick the components you need or run the full stack. 

***

### 🛡️ The Philosophy: Brutally Honest Infrastructure

Tarka is built on a simple premise: **AI is flaky, and silently failing open is a great way to get sued.** 

Instead of treating LLMs and ML models as magic black boxes that autonomously run your risk operations, Tarka treats them as unreliable dependencies. We prioritize boring, durable database logs and strict execution limits over marketing-driven autonomy. If you need to explain to a regulator exactly why a transaction was blocked, backed by a relational database record and a fail-closed execution log, this is for you.

***

### 🏗️ Architecture: The Durable Data Plane

Tarka separates the Decision Plane (Fast/Stateless) from the Audit Plane (Durable/Immutable). We don't believe in authoritative in-memory state.

*   **Decision Plane (Hetu):** Stateless FastAPI workers that evaluate rules in real-time.
*   **Audit Plane (Lekh):** Every rule change, SAR intent, and sanctions screening is durably persisted to PostgreSQL via Alembic-managed migrations *before* a 200 OK is returned.
*   **Analytics Plane (Kala):** Historical decisioning data is synced to ClickHouse. All analytical queries are server-side execution-bounded (`max_execution_time`) to prevent warehouse latency from cascading into the API.
*   **Forensic Plane (Shadow):** Tarka is fully integrated with [Shadow](https://github.com/pamu512/shadow), a local-first agentic AI designed for deep fraud forensics. While Tarka manages the durable audit plane and real-time signals, Shadow allows investigators to run intensive, air-gapped analysis using local LLMs (Llama 3.2, Qwen3-VL) via Ollama.

***

### 🚦 Resilience & Observability

Tarka is designed for production environments where dependencies are expected to fail.

*   **Fail-Closed Logic:** If ClickHouse or your LLM provider is down, Tarka returns a `503 Service Unavailable`. 
*   **Structured Reason Codes:** All 5xx errors include a `reason_code` to allow for granular alerting and automated remediation in your SOC. 
*   **Deterministic Fallbacks:** We explicitly disabled "template-based" SQL fallbacks. If the logic can't be proved, the system fails-closed to protect the integrity of your data.

```json
// Example Fail-Closed Response
{
  "error": "Service Unavailable",
  "reason_code": "LLM_ENGINE_OFFLINE",
  "message": "Transaction blocked: Integrity check failed due to upstream timeout."
}
```

***

### 🚥 What's Actually Shipping (The Reality Check)

Tarka is modular. CLI slugs stay stable; the Sanskrit codenames represent the product story. Here is the brutal truth about the integrity status of each module on `master` today:

| Slug | Codename | Integrity Status |
| :--- | :--- | :--- |
| `core` | **Hetu** | **Audit-Ready:** JSON/SQL evaluation with durable GitOps approval tokens. |
| `analytics` | **Kala** | **Bounded:** Real ClickHouse OLAP with 5s execution caps. |
| `integration` | **Setu** | **Verified:** 12-source OSINT with Postgres-backed Screening Logs. |
| `cases` | **Lekh** | **Durable Intent:** SAR generation with persistent filing state machines. |
| `graph` | **Jaala** | **In-Memory/Lite:** Entity graph and community detection (Neo4j). |
| `agent` | **Saarthi** | **Tool-Use Loop:** AI investigation copilot with strict execution boundaries. |
| `forensics` | **Shadow** | **Local-First:** Agentic forensics and logic stress-testing via Ollama. |

#### OSS vs. Saarthi Pro
We are transparent about the commercial model. The core investigation agent ships here in OSS.
*   **OSS (`investigation-agent`):** Best for teams who want the full stack and self-hosted ops. You own the upgrades, uptime, and compliance mapping.
*   **Saarthi Pro:** Best for enterprise procurement. Includes SLAs, governance roadmaps, vendor support, and commercial terms.

***

### 🕵️ Local Forensics & Stress Testing

For high-sensitivity investigations, Tarka integrates with **[Shadow](https://github.com/pamu512/shadow)**. Shadow is a specialized, local tool-use interface that pulls data from Tarka's `inference_context` and runs it through local models for forensic data reconstruction.

*   **Logic Stress-Testing:** Use Shadow to find edge cases in your existing Tarka rule sets before they hit production.
*   **Hardware-Aware:** Designed to run efficiently on consumer-grade hardware supporting Llama 3.2 or Qwen3-vl:30b through Ollama. Optimized for 16GB+ Unified Memory systems. We don't just blindly call the OpenAI API.
*   **Air-Gapped Analysis:** Perform entity resolution and link analysis without sending sensitive PII to a third-party LLM provider. Sensitive case data stays on your machine during deep-dive forensics.

***

### 📡 The Signals We Actually Collect

#### 1. OSINT Enrichment (Integration Ingress)
Built-in OSINT enrichment queries 12 sources in parallel (9 work without API keys):
*   **IP Data:** Shodan InternetDB (Open ports/CVEs), AbuseIPDB, GreyNoise, IPinfo Lite, ip-api.com.
*   **Email Data:** EmailRep.io, Gravatar, Have I Been Pwned, DNS MX validation.
*   **Phone/Domain/Identity:** NumVerify, RDAP, GitHub profile discovery.

#### 2. SDK Device Signals
All SDKs collect device signals and send them as `device_context` with each evaluation:
*   **Evasion Detection:** Emulator/simulator detection, VPN detection (WebRTC leaks, utun interfaces), Location spoofing.
*   **Bot & Automation:** Behavioral entropy, bot User-Agents, typing cadence, mouse dynamics.
*   **App Integrity:** Certificate hash verification, Play Integrity (Android), App Attest (iOS).

***

### 🛠️ Install & Run

Tarka is built to run locally via Docker Compose or be installed via our Python CLI.

```bash
# Clone the repository
git clone https://github.com/pamu512/tarka.git
cd tarka

# Option 1: Minimal setup (Decision + Case + OSINT + UI + Postgres Audit; no Neo4j)
python tarka.py install --lite

# Option 2: Interactive installer (pick your modules)
python tarka.py install

# Option 3: Install as a Python library
pip install tarka[lite]      # Core + cases
pip install tarka[standard]  # Core + graph + ML + cases + OSINT
```

**Managing Services:**
```bash
python tarka.py start              # Start all installed modules
python tarka.py logs -f            # Follow all logs
python tarka.py status             # Show running services & health
```

**Prebuilt Sandbox (Docker Compose):**
```bash
docker compose -f https://raw.githubusercontent.com/pamu512/tarka/master/deploy/docker-compose.sandbox.yml up -d
```
*   Frontend: `http://localhost:3000`
*   Decision API: `http://localhost:8000/v1/health`
*   Integration Ingress: `http://localhost:8003/v1/health`

***

### 🔒 Security, Compliance & Licensing

*   **Security Hygiene:** We run strict CI/CD gates. GitHub Actions enforces Ruff linting, pytest coverage (≥48% gate), Trivy filesystem/image scanning, and TruffleHog secret scanning on every PR.
*   **License:** Application code in this repository is **Apache-2.0**. 
*   **The AGPL Warning:** If you run the full graph stack, be aware that **Neo4j is AGPL-3.0**. If your legal team blocks AGPL, use the `--lite` installation path or review `LICENSE-DEPENDENCIES.md` for Apache-friendly alternatives.