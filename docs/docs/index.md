# Tarka

> **Prove every signal.**

**Open-source, modular fraud detection platform.**

Tarka gives engineering teams a production-ready fraud detection pipeline they fully own. Instead of paying per-API-call to a black-box vendor, you deploy the components you need — real-time rule evaluation, ML model inference, entity-graph analytics, case management, and investigation tooling — inside your own infrastructure. Every decision is auditable, every rule is version-controlled JSON, and every model can be swapped without a deploy.

The platform is designed around composability. Run just the Decision API with Redis for a lightweight scoring layer, or spin up the full stack with Neo4j graph analytics, ONNX model serving, NATS streaming, ClickHouse analytics, and an AI-powered investigation agent. Docker Compose profiles let you pick exactly what you need, and Helm charts are included for Kubernetes.

---

## What’s new (April 2026)

- **Investigation copilot (OSS):** **`GET /v1/ready`** and **`GET /v1/setup`**, production diagnostics on **`GET /v1/health`**, **workflow-aware** **`POST /v1/chat`**, case-summary **PDF** / turn-bundle exports, and production guardrails — see [Integration changelog](guides/CHANGELOG_INTEGRATION.md) and [Investigation Agent project](projects/investigation-agent-project.md).
- **Collaboration chat bridge:** Slack, Teams, and Lark → agent with **attachments** (incl. **xlsx**), **SSRF-safe URL** enrichment, **workflow directives**, and **ingress rate limits** — [bridge README](../../services/collaboration-chat-bridge/README.md) and [Collaboration chat & cloud](guides/investigation-collaboration-chat-aws-azure.md).
- **Tarka repo:** Default development branch is **`master`**; release cadence and tags are unchanged — [Release schedule](../../RELEASE_SCHEDULE.md) (repository root).

---

## Key Features

- **Real-time fraud scoring** — Sub-50ms decisions combining JSON rules, ML models, OPA policies, and device signals into a single score.
- **Entity graph** — Neo4j-backed graph that automatically links accounts, devices, sessions, and payments. Built-in community detection, fraud ring identification, and risk propagation.
- **ML model serving** — ONNX model registry with versioned deployments, A/B traffic splitting, and automatic heuristic fallback. Train models with the included pipeline or bring your own.
- **Case management** — Full investigation workflow with SLA tracking, workflow automation, audit trails, labels, comments, and WebSocket live feeds.
- **Device signal SDKs** — **TypeScript** (browser), **Python** (server), **Kotlin** ([Android SDK](sdks/android.md)), and **Swift** ([iOS SDK](sdks/ios.md)) ship in-repo with the same `device_context` contract — see [SDK scorecard](guides/sdk-scorecard-2026-01.md) and [Mobile SDK project](projects/sdk-mobile-project.md).
- **Regulated markets (optional)** — fintech, banking, crypto-adjacent, and similar deployments can follow the **[regulated markets feature pack](guides/feature-pack-regulated-markets.md)** checklist (ingress integrity, attestation, audit, self-hosted data boundaries). For **SOC 2 / PCI / ISO** orientation (readiness vs certification), see **[compliance readiness](guides/compliance-readiness-soc2-pci-iso.md)**. Mobile **`device_context.attestation`** uses a shared vocabulary — **[mobile attestation taxonomy](guides/mobile-attestation-taxonomy.md)**.
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

    Deploy to production with Docker Compose profiles or Helm on Kubernetes. **[OSS track closure checklist](guides/oss-track-issue-closure-evidence-2026-04.md)** (#31–#54 merge evidence). **[Policy DAG (OSS #31)](./guides/policy-dag-oss-31.md)** (canary, shadow, champion–challenger audit). **[Typology / parity / graph checkpoints (#34, #48, #49)](./guides/oss-typology-parity-graph-34-48-49.md)**. **[Rule ops N1–N4](./guides/rules-operations-n1-n4.md)** (no-code UI, governance header, rule telemetry). **[v1.2.5 backlog status](./guides/v1.2.5-execution-backlog-status.md)** (shipped vs deferred). **[Close epics #4–#12 (paste-ready comments)](./guides/github-issue-closure-epics-4-12.md)**. **[ETL Bronze/Silver/Gold](./guides/etl-bronze-silver-gold.md)** (ingest DLQ, silver checks). **[Service SLOs (v1)](./guides/service-slos-v1.md)** · **[Late arrival & watermarks](./guides/late-arrival-watermarks.md)**.

- :material-robot: **[Investigation copilot (Saarthi) & Saarthi Pro](guides/saarthi-pro-vs-oss.md)**

    LLM tool-use loop against case, graph, and decision APIs. Open reference ships in-repo; **Saarthi Pro** is the commercial packaging (support, adapters, procurement). Start with **vs OSS**.

</div>
