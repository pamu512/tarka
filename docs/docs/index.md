# Tarka

> **Prove every signal.**

**Open-source, modular fraud detection platform.**

Tarka gives engineering teams a production-ready fraud detection pipeline they fully own. Instead of paying per-API-call to a black-box vendor, you deploy the components you need — real-time rule evaluation, ML model inference, entity-graph analytics, case management, and investigation tooling — inside your own infrastructure. Every decision is auditable, every rule is version-controlled JSON, and every model can be swapped without a deploy.

The platform is designed around composability. Run just the Decision API with Redis for a lightweight scoring layer, or spin up the full stack with Neo4j graph analytics, ONNX model serving, NATS streaming, ClickHouse analytics, and an AI-powered investigation agent. Docker Compose profiles let you pick exactly what you need, and Helm charts are included for Kubernetes.

---

## Key Features

- **Real-time fraud scoring** — Sub-50ms decisions combining JSON rules, ML models, OPA policies, and device signals into a single score.
- **Entity graph** — Neo4j-backed graph that automatically links accounts, devices, sessions, and payments. Built-in community detection, fraud ring identification, and risk propagation.
- **ML model serving** — ONNX model registry with versioned deployments, A/B traffic splitting, and automatic heuristic fallback. Train models with the included pipeline or bring your own.
- **Case management** — Full investigation workflow with SLA tracking, workflow automation, audit trails, labels, comments, and WebSocket live feeds.
- **Device signal SDKs** — TypeScript (browser), Python (server), Android (Kotlin), and iOS (Swift) SDKs that collect emulator detection, VPN detection, bot detection, location spoofing, and app integrity attestation.
- **Streaming ingestion** — NATS JetStream-backed event pipeline for high-throughput async processing with at-least-once delivery.
- **Workflow automation** — JSON-defined workflows that auto-escalate, route, label, and webhook based on triggers and conditions.
- **Full audit trail** — Every decision, rule hit, score, and case mutation is recorded in Postgres with trace IDs for end-to-end observability.

---

## Tarka vs. Commercial Alternatives

| Capability | Tarka | Sift | Sardine | Marble |
|---|---|---|---|---|
| Self-hosted | **Yes** | No | No | No |
| Source available | **Apache-2.0** | No | No | No |
| Per-decision pricing | **Free** | ~$0.01–0.05 | ~$0.01–0.03 | ~$0.02 |
| Custom rules engine | **JSON + OPA** | Limited UI | Limited | Yes |
| Graph analytics | **Neo4j built-in** | Limited | No | Yes |
| ML model BYO | **ONNX registry** | No | No | Limited |
| Device signals | **4 platform SDKs** | JS only | JS + mobile | JS only |
| Case management | **Built-in** | Add-on | Add-on | Built-in |
| Deployment control | **Full** | None | None | None |

---

## Get Started

<div class="grid cards" markdown>

- :material-rocket-launch: **[Quickstart](quickstart.md)**

    Get the platform running locally in under 5 minutes with Docker Compose.

- :material-sitemap: **[Architecture](architecture.md)**

    Understand how services connect and data flows through the system.

- :material-book-open-variant: **[Rule Authoring](guides/rules.md)**

    Write your first fraud detection rule pack in JSON.

- :material-kubernetes: **[Deployment Guide](guides/deployment.md)**

    Deploy to production with Docker Compose profiles or Helm on Kubernetes.

</div>
