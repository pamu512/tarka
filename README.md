# Tarka: Audit-First Fraud Infrastructure

> **Prove every signal. Because detection without auditability is a liability.**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Engine](https://img.shields.io/badge/Core-Rust-orange.svg)](services/rule-engine/)
[![API](https://img.shields.io/badge/Services-FastAPI-green.svg)](services/core-api/)

Tarka — from Sanskrit *तर्क (tarka)*, the method of logical hypothesis testing. 

In modern risk operations, a fraud signal is merely a hypothesis. Tarka is built on the principle that a hypothesis is only "proven" once it is written to a durable, immutable audit log. Most systems have a detection problem; Tarka solves the **auditability problem** that plagues operations and regulatory compliance.



---

## 🛡️ The Philosophy: Brutal Transparency

Tarka is not a black-box "turnkey" solution. It is fraud infrastructure designed to be maintained by engineering teams who demand "whitebox" transparency.

* **Audit-First, Detection-Second:** If it isn't in the database, it didn't happen. We prioritize durable relational records over ephemeral in-memory scores.
* **AI as an Unreliable Dependency:** We treat LLMs and ML models as flaky dependencies. Tarka wraps them in strict execution boundaries, fail-closed logic, and persistent provenance logs.
* **Infrastructure, Not a Tool:** Tarka is designed to be the foundational architecture that scales with your company, ensuring you save on operational headcount by dedicating resources to technical "proof" rather than manual guesswork.

---

## 🏗️ Architecture: The Provenance Stack

Tarka separates concerns into distinct "Planes" to ensure that high-velocity decisioning never compromises the integrity of the audit trail.

### 1. Decision Plane (Hetu)
Stateless FastAPI microservices. Real-time rule evaluation is offloaded to a **native Rust engine** (`tarka_rule_engine`) via PyO3 for sub-millisecond performance without the overhead of Python's GIL.

### 2. Audit Plane (Lekh)
The authoritative source of truth. Every rule change, SAR intent, and signal evaluation is durably persisted to PostgreSQL. We use `fail-closed` logic: if the audit log cannot be written, the transaction is blocked.

### 3. Analytics Plane (Kala)
Historical data is synced to **ClickHouse** for OLAP workloads. All analytical queries are server-side execution-bounded (`max_execution_time`) to prevent warehouse latency from cascading into the real-time API.

### 4. Forensic Plane (Shadow)
A local-first, agentic AI suite (via Ollama) designed for deep-dive forensics. Shadow allows investigators to run air-gapped, intensive analysis on sensitive PII without sending data to third-party LLM providers.

---

## 🚦 Module Integrity Matrix

| Slug | Codename | Status | Technical Reality |
| :--- | :--- | :--- | :--- |
| **core** | **Hetu** | `Audit-Ready` | Rust-backed JSON evaluation; GitOps approval tokens. |
| **analytics** | **Kala** | `Bounded` | ClickHouse OLAP with strict 5s execution caps. |
| **graph** | **Jaala** | `Durable` | JanusGraph (Apache-2.0) default; Neo4j (AGPL) optional. |
| **signals** | **Anumana** | `Materialized` | Async OSINT over NATS; Redis-backed temporal features. |
| **cases** | **Lekh** | `Persistent` | State-machine driven SAR generation. |
| **forensics**| **Shadow** | `Local-First` | Local LLM tool-use via Ollama (Llama 3.2 / Qwen3). |

---

## 🛠️ Technical Deep Dive

### Rust Rule Engine
The core evaluation logic lives in `services/rule-engine/`. It is a standalone Rust crate exposed as a Python C-extension.
```bash
pip install maturin
cd services/rule-engine
maturin develop --release
```

### Fail-Closed Resilience
Tarka does not "guess" when dependencies fail. If a critical path (Postgres, Redis, or the Rule Engine) is unreachable, the system returns a structured `503 Service Unavailable` with a specific `reason_code`.
```json
{
  "error": "Service Unavailable",
  "reason_code": "AUDIT_LOG_UNREACHABLE",
  "message": "Integrity check failed: Cannot prove signal provenance."
}
```

---

## 🚀 Getting Started

Tarka is modular. Install only what you need to support your existing infrastructure.

### Option 1: The Infrastructure CLI
```bash
# Clone the repo
git clone https://github.com/pamu512/tarka.git
cd tarka

# Interactive setup to pick your planes
python tarka.py install
python tarka.py start
```

### Option 2: Docker Sandbox
For a pre-configured environment including the UI, Postgres, and the Decision API:
```bash
docker compose -f deploy/docker-compose.sandbox.yml up -d
```

---

## ⚖️ License & Compliance

* **Application Code:** [Apache-2.0](LICENSE)
* **Graph Backend:** Defaults to JanusGraph (Apache-2.0). Usage of Neo4j triggers AGPL-3.0 obligations.
* **Security Hygiene:** Every PR is gated by Ruff formatting, Trivy vulnerability scanning, and TruffleHog secret detection.

---

**Tarka is built for the engineer who knows that "trust me" is not a valid security policy.** [Contribute](CONTRIBUTING.md) | [Documentation](docs/) | [Security](SECURITY.md)
