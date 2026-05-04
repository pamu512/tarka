# Architecture

Tarka is a collection of loosely coupled microservices connected via HTTP and message streaming. Each service is independently deployable and horizontally scalable.

**Enterprise parity surfaces** (schemaless ingest on :8007, offline CSV backfill, visual rules + backtest SQL preview, vendor registry, embedded KPIs, case queue routing, SAR validation): [Enterprise parity (ingest, rules, vendors)](guides/competitor-parity.md). Environment table: [`../architecture/competitor-parity-env.md`](../architecture/competitor-parity-env.md).

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
│   ┌──────────────────────────┐         ┌──────────────────────────┐    │
│   │  Core API :8000        │◄────────│  Data plane :8007        │    │
│   │  (/decisions sync)     │         │  (async via NATS)        │    │
│   └──────────┬─────────────┘         └──────────┬───────────────┘    │
│              │                                   │                     │
│              │                       ┌───────────▼──────────┐          │
│              │                       │   NATS JetStream     │          │
│              │                       │   :4222              │          │
│              │                       └──────────────────────┘          │
└──────────────┼─────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Processing Layer                                 │
│                                                                         │
│   ┌────────────────┐  ┌────────────────┐  ┌────────────────────────┐   │
│   │  JSON Rules    │  │  OPA :8181     │  │  Signal API :8004      │   │
│   │  (built-in)    │  │  (optional)    │  │  (/ml + Triton :8020)  │   │
│   └────────────────┘  └────────────────┘  └──────────┬─────────────┘   │
│                                                        │               │
│   ┌────────────────┐  ┌────────────────┐  ┌────────────────────────┐   │
│   │  /features     │  │  Redis :6379   │  │  Postgres :5432        │   │
│   │  (/counters)   │  │  (tags, aggs,  │  │  (audit, cases, graph) │   │
│   │                │  │   scores)      │  │                        │   │
│   └────────────────┘  └────────────────┘  └────────────────────────┘   │
│                                                                         │
│   ┌────────────────┐  ┌────────────────┐  ┌────────────────────────┐   │
│   │  Triton :8020  │  │                │  │                        │   │
│   │  (ONNX models) │  │                │  │                        │   │
│   └────────────────┘  └────────────────┘  └────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        Analytics & Graph Layer                           │
│                                                                         │
│   ┌────────────────────────┐  ┌────────────────────────┐               │
│   │  Graph Service :8001   │  │  Data plane :8007      │               │
│   │  (entity resolution,   │  │  (ClickHouse writer)   │               │
│   │   community detection, │  │                        │               │
│   │   fraud rings)         │  └──────────┬─────────────┘               │
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
│   │  Core API :8000        │  │  Investigation Agent   │               │
│   │  (/cases workflows)    │  │  :8006                 │               │
│   │                        │  │  (LLM tool-use loop)   │               │
│   └────────────────────────┘  └────────────────────────┘               │
│                                                                         │
│   ┌────────────────────────┐  ┌────────────────────────┐               │
│   │  Integration Ingress   │  │  GraphQL Gateway       │               │
│   │  :8003                 │  │  :8010                 │               │
│   │  (KYC adapters)        │  │  (unified API)         │               │
│   └────────────────────────┘  └────────────────────────┘               │
│                                                                         │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │  (Slack / Teams / Lark ingress lives on investigation-agent  │     │
│   │   :8006 under /v1/chat/…)                                     │     │
│   └──────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Service Reference


| Service                 | Port | Technology          | Purpose                                                       | Dependencies                          |
| ----------------------- | ---- | ------------------- | ------------------------------------------------------------- | ------------------------------------- |
| **Core API**            | 8000 | Python / FastAPI    | **Macroservice:** decision (`/decisions`) + case (`/cases`); scoring, typology DSL, **evaluation posture** + **SLO**, attestation, workflows | Postgres, Redis, optional Signal API, Graph, OPA |
| **Graph Service**       | 8001 | Python / FastAPI    | Entity graph, tag storage, community/ring detection           | Postgres (Apache AGE)                 |
| **Integration Ingress** | 8003 | Python / FastAPI    | KYC webhook adapters, sanctions screening                     | Postgres                              |
| **Signal API**          | 8004 | Python / FastAPI    | **Macroservice:** features, ML, calibration, counters, location (mounted paths) | Redis, optional Triton                |
| **Investigation Agent** | 8006 | Python / FastAPI    | LLM copilot; **POST /v1/chat**; embedded **Slack / Teams / Lark** + plugin proxy under **`/v1/chat/…`** ([API ref](api-reference.md#investigation-agent), [chat contract](api-reference.md#collaboration-chat-bridge)); **POST /v1/evidence/summary** | Core API, Graph Service, OpenAI       |
| **Data plane**          | 8007 | Python / FastAPI    | Event ingest + analytics sink (combined)                      | NATS, Core API, optional ClickHouse   |
| **GraphQL Gateway**     | 8010 | Python / Strawberry | Unified GraphQL API across services                           | Core API (mount-aware URLs), Graph Service |
| **Frontend**            | 3000 | React / Vite        | Investigation UI, dashboard, graph explorer                   | Core API, Graph Service               |

Logical modules still live under `services/decision-api`, `services/case-api`, `services/feature-service`, `services/ml-scoring`, etc. Per-service docs: [Decision API](services/decision-api.md) · [Graph Service](services/graph-service.md) · [Case API](services/case-api.md) · [Feature Service](services/feature-service.md) · [ML Scoring](services/ml-scoring.md) · [Investigation Agent](services/investigation-agent.md). **Collaboration chat** is embedded in the agent — see [API Reference — Collaboration chat (embedded)](api-reference.md#collaboration-chat-bridge) and [Collaboration chat & cloud](guides/investigation-collaboration-chat-aws-azure.md).

The analyst UI uses a **single HTTP entry point** in the repo (`frontend/src/api/client.ts`): a barrel that re-exports shared types, `request()`, and per-service API objects from `frontend/src/api/modules/`. For the layout (what changed when the former monolithic `client.ts` was split), see [Frontend project](projects/frontend-project.md) (section **UI HTTP client**).

### Infrastructure


| Component          | Port                         | Purpose                                           |
| ------------------ | ---------------------------- | ------------------------------------------------- |
| **Postgres**       | 5432                         | Audit records, case data, integration state, Apache AGE graph |
| **Redis**          | 6379                         | Tags, cached scores, real-time aggregates, nonces |
| **NATS JetStream** | 4222 / 8222 (monitoring)     | Event streaming with at-least-once delivery       |
| **ClickHouse**     | 8123 (HTTP) / 9000 (native)  | Columnar analytics storage                        |
| **OPA**            | 8181                         | Optional external policy engine                   |
| **Triton**         | 8020 (HTTP) / 8021 (gRPC)    | High-performance ONNX model inference             |


---

## Data Flow

### Synchronous Path (Decision API direct)

```
Client SDK
  │
  ▼
Core API /decisions/v1/decisions/evaluate   (or legacy standalone decision-api)
  │
  ├─── Extract device signal tags (sdk:emulator, sdk:vpn, sdk:bot, ...)
  ├─── Fetch existing tags from Redis
  ├─── Compute real-time aggregates from Redis sorted sets
  ├─── Build feature snapshot (via Signal API /features or inline)
  ├─── Normalize currency (if applicable)
  │
  ├─── [parallel] Evaluate JSON rules → rule_hits + tags + score_delta
  ├─── [parallel] Evaluate OPA policies → additional rule_hits + tags
  ├─── [parallel] Call Signal API /ml → ml_score (0–100)
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

### Asynchronous Path (data plane ingest)

```
Client
  │
  ▼
Data plane /v1/events
  │
  ▼
NATS JetStream (fraud.events.{tenant}.{type})
  │
  ▼
Consumer Loop → Core API /decisions/v1/decisions/evaluate
  │
  ▼
Data plane analytics path → ClickHouse
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


