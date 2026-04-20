# Architecture

Tarka is a collection of loosely coupled microservices connected via HTTP and message streaming. Each service is independently deployable and horizontally scalable.

---

## System Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Client Layer                                  │
│                                                                         │
│   ┌──────────────┐  ┌──────────────┐  ┌────────────┐  ┌────────────┐  │
│   │ TS SDK (Web) │  │ Python SDK   │  │ Android SDK│  │  iOS SDK   │  │
│   │  :browser    │  │  :server     │  │  :kotlin   │  │  :swift    │  │
│   └──────┬───────┘  └──────┬───────┘  └─────┬──────┘  └─────┬──────┘  │
└──────────┼─────────────────┼────────────────┼───────────────┼──────────┘
           │                 │                │               │
           ▼                 ▼                ▼               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Ingestion Layer                                │
│                                                                         │
│   ┌──────────────────────┐         ┌──────────────────────┐            │
│   │  Decision API :8000  │◄────────│  Event Ingest :8007  │            │
│   │  (sync evaluation)   │         │  (async via NATS)    │            │
│   └──────────┬───────────┘         └──────────┬───────────┘            │
│              │                                 │                        │
│              │                     ┌───────────▼──────────┐            │
│              │                     │   NATS JetStream     │            │
│              │                     │   :4222              │            │
│              │                     └──────────────────────┘            │
└──────────────┼─────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Processing Layer                                 │
│                                                                         │
│   ┌────────────────┐  ┌────────────────┐  ┌────────────────────────┐   │
│   │  JSON Rules    │  │  OPA :8181     │  │  ML Scoring :8005      │   │
│   │  (built-in)    │  │  (optional)    │  │  (heuristic + ONNX)    │   │
│   └────────────────┘  └────────────────┘  └────────────────────────┘   │
│                                                                         │
│   ┌────────────────┐  ┌────────────────┐  ┌────────────────────────┐   │
│   │  Feature Svc   │  │  Redis :6379   │  │  Postgres :5432        │   │
│   │  :8004         │  │  (tags, aggs,  │  │  (audit, cases)        │   │
│   │                │  │   scores)      │  │                        │   │
│   └────────────────┘  └────────────────┘  └────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Analytics & Graph Layer                           │
│                                                                         │
│   ┌────────────────────────┐  ┌────────────────────────┐               │
│   │  Graph Service :8001   │  │  Analytics Sink :8008   │              │
│   │  (entity resolution,   │  │  (ClickHouse writer)    │              │
│   │   community detection, │  │                         │              │
│   │   fraud rings)         │  └──────────┬──────────────┘              │
│   └──────────┬─────────────┘             │                             │
│              │                 ┌─────────▼──────────┐                  │
│   ┌──────────▼─────────────┐  │  ClickHouse :8123  │                  │
│   │  Neo4j :7687           │  │  (event analytics)  │                  │
│   │  (entity graph)        │  └────────────────────┘                  │
│   └────────────────────────┘                                           │
└─────────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      Investigation Layer                                │
│                                                                         │
│   ┌────────────────────────┐  ┌────────────────────────┐               │
│   │  Case API :8002        │  │  Investigation Agent   │               │
│   │  (cases, workflows,    │  │  :8006                 │               │
│   │   SLA, audit trail)    │  │  (LLM tool-use loop)   │               │
│   └────────────────────────┘  └────────────────────────┘               │
│                                                                         │
│   ┌────────────────────────┐  ┌────────────────────────┐               │
│   │  Integration Ingress   │  │  GraphQL Gateway       │               │
│   │  :8003                 │  │  :8010                 │               │
│   │  (KYC adapters)        │  │  (unified API)         │               │
│   └────────────────────────┘  └────────────────────────┘               │
│                                                                         │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │  Collaboration chat bridge :8009 (Slack / Teams / Lark)      │     │
│   └──────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Service Reference


| Service                 | Port | Technology          | Purpose                                                       | Dependencies                          |
| ----------------------- | ---- | ------------------- | ------------------------------------------------------------- | ------------------------------------- |
| **Decision API**        | 8000 | Python / FastAPI    | Real-time fraud scoring, typology DSL, **evaluation posture** + **SLO** for trust/ops UI ([API ref](api-reference.md#trust-ops-readiness)), attestation | Postgres, Redis                       |
| **Graph Service**       | 8001 | Python / FastAPI    | Entity graph, tag storage, community/ring detection           | Neo4j                                 |
| **Case API**            | 8002 | Python / FastAPI    | Investigation cases, workflows, SLA, audit trail              | Postgres, Graph Service (optional)    |
| **Integration Ingress** | 8003 | Python / FastAPI    | KYC webhook adapters, sanctions screening                     | Postgres                              |
| **Feature Service**     | 8004 | Python / FastAPI    | Velocity reads, feature snapshots, **parity verify** ([OSS #48](guides/oss-typology-parity-graph-34-48-49.md)) | Redis (same aggregate keyspace as Decision API) |
| **ML Scoring**          | 8005 | Python / FastAPI    | ONNX + heuristic model inference, A/B testing                 | —                                     |
| **Investigation Agent** | 8006 | Python / FastAPI    | LLM copilot; **POST /v1/evidence/summary** (deterministic citations + next actions, [API ref](api-reference.md#investigation-agent)) | Case API, Graph Service, Decision API, OpenAI |
| **Event Ingest**        | 8007 | Python / FastAPI    | High-throughput async event ingestion                         | NATS, Decision API                    |
| **Analytics Sink**      | 8008 | Python / FastAPI    | Streams events to ClickHouse for analytics                    | NATS, ClickHouse                      |
| **Collaboration chat bridge** | 8009 | Python / FastAPI | Slack / Teams / Lark ingress → investigation-agent ([API ref](api-reference.md#collaboration-chat-bridge)) | Investigation Agent                   |
| **GraphQL Gateway**     | 8010 | Python / Strawberry | Unified GraphQL API across services                           | Decision API, Case API, Graph Service |
| **Frontend**            | 3000 | React / Vite        | Investigation UI, dashboard, graph explorer                   | Case API, Decision API                |

Per-service overview pages (ports, primary endpoints, doc pointers): [Decision API](services/decision-api.md) · [Graph Service](services/graph-service.md) · [Case API](services/case-api.md) · [Feature Service](services/feature-service.md) · [ML Scoring](services/ml-scoring.md) · [Investigation Agent](services/investigation-agent.md). **Collaboration chat bridge** has no separate `services/*.md` page — see [API Reference — Collaboration Chat Bridge](api-reference.md#collaboration-chat-bridge) and [Collaboration chat & cloud](guides/investigation-collaboration-chat-aws-azure.md).

The analyst UI uses a **single HTTP entry point** in the repo (`frontend/src/api/client.ts`): a barrel that re-exports shared types, `request()`, and per-service API objects from `frontend/src/api/modules/`. For the layout (what changed when the former monolithic `client.ts` was split), see [Frontend project](projects/frontend-project.md) (section **UI HTTP client**).

### Infrastructure


| Component          | Port                         | Purpose                                           |
| ------------------ | ---------------------------- | ------------------------------------------------- |
| **Postgres**       | 5432                         | Audit records, case data, integration state       |
| **Redis**          | 6379                         | Tags, cached scores, real-time aggregates, nonces |
| **Neo4j**          | 7687 (bolt) / 7474 (browser) | Entity graph storage                              |
| **NATS JetStream** | 4222 / 8222 (monitoring)     | Event streaming with at-least-once delivery       |
| **ClickHouse**     | 8123 (HTTP) / 9000 (native)  | Columnar analytics storage                        |
| **OPA**            | 8181                         | Optional external policy engine                   |


---

## Data Flow

### Synchronous Path (Decision API direct)

```
Client SDK
  │
  ▼
Decision API /v1/decisions/evaluate
  │
  ├─── Extract device signal tags (sdk:emulator, sdk:vpn, sdk:bot, ...)
  ├─── Fetch existing tags from Redis
  ├─── Compute real-time aggregates from Redis sorted sets
  ├─── Build feature snapshot (via Feature Service or inline)
  ├─── Normalize currency (if applicable)
  │
  ├─── [parallel] Evaluate JSON rules → rule_hits + tags + score_delta
  ├─── [parallel] Evaluate OPA policies → additional rule_hits + tags
  ├─── [parallel] Call ML Scoring → ml_score (0–100)
  │
  ├─── Blend scores (average | max | rules_only)
  ├─── Apply decision thresholds (deny ≥ 80, review ≥ 50)
  ├─── Merge tags into Redis
  │
  ├─── [background] Write audit record to Postgres
  ├─── [background] Upsert entities + links in Graph Service
  ├─── [background] Broadcast to WebSocket subscribers
  │
  └─── Return: { trace_id, decision, score, tags, rule_hits, reasons, ml_score }
```

### Asynchronous Path (Event Ingest)

```
Client
  │
  ▼
Event Ingest /v1/events
  │
  ▼
NATS JetStream (fraud.events.{tenant}.{type})
  │
  ▼
Consumer Loop → Decision API /v1/decisions/evaluate
  │
  ▼
Analytics Sink → ClickHouse
```

---

## Technology Choices


| Area               | Choice                     | Rationale                                                             |
| ------------------ | -------------------------- | --------------------------------------------------------------------- |
| **Language**       | Python 3.11+               | Async FastAPI for all services, broad ML ecosystem                    |
| **API framework**  | FastAPI + Pydantic         | Auto-generated OpenAPI docs, async by default, request validation     |
| **Relational DB**  | PostgreSQL 16              | Battle-tested, JSONB for flexible payloads, async driver (asyncpg)    |
| **Cache / state**  | Redis 7                    | Sub-millisecond tag lookups, sorted sets for real-time aggregates     |
| **Graph DB**       | Neo4j 5 Community          | Cypher query language, no GDS plugin required (pure Cypher analytics) |
| **ML runtime**     | ONNX Runtime               | Vendor-neutral model format, CPU inference, easy model swap           |
| **Message broker** | NATS JetStream             | Lightweight, built-in persistence, at-least-once delivery             |
| **Analytics**      | ClickHouse                 | Columnar storage optimized for aggregate queries on event data        |
| **Policy engine**  | Open Policy Agent          | Optional, Rego language for complex compliance rules                  |
| **Frontend**       | React + Vite + TailwindCSS | Fast dev iteration, TypeScript, modern component architecture         |
| **Container**      | Docker + Compose profiles  | Profile-based composition lets you pick only what you need            |
| **Orchestration**  | Helm charts for Kubernetes | Production-grade deployment with `values.yaml` toggles                |


