# Deployment Guide

This guide covers deploying Tarka from local development through production, including Docker Compose profiles, Kubernetes with Helm, environment variable reference, scaling, and security hardening.

**Public cloud (Kubernetes):** For AWS and Azure–specific service mapping, ingress, managed Postgres/Redis, and secrets patterns, see **[Deploying on AWS](./deployment-aws.md)** and **[Deploying on Azure](./deployment-azure.md)**.

**See also:** [Service ports & OpenAPI index](./service-ports.md) — default ports, Compose DNS names, and contract file mapping.

**Runtime tiers:** [Deployment profiles — Community vs Pro](./deployment-profiles-community-vs-pro.md) — `docker-compose.lite.yml` vs profile-based `docker-compose.yml`, env matrix, limitations (**#38**).

---

## Docker Compose Profiles

The `deploy/docker-compose.yml` file uses Compose profiles so you can pick exactly the components you need.

### Available Profiles

| Profile | Services Included |
|---|---|
| `core` | Decision API, Postgres, Redis |
| `graph` | Graph Service, Neo4j |
| `cases` | Case API |
| `ml` | ML Scoring, Feature Service |
| `streaming` | Event Ingest, NATS JetStream |
| `analytics` | Analytics Sink, ClickHouse |
| `integration` | Integration Ingress |
| `agent` | Investigation Agent |
| `gateway` | GraphQL Gateway |
| `opa` | Open Policy Agent |
| `full` | All of the above |

### Usage Examples

**Core only** — minimum viable fraud scoring:

```bash
cd deploy
docker compose --profile core up -d
```

**Core + graph + cases** — scoring with graph analytics and investigation:

```bash
docker compose --profile core --profile graph --profile cases up -d
```

**Core + ML** — scoring with machine learning:

```bash
docker compose --profile core --profile ml up -d
```

**Full stack** — everything:

```bash
cp .env.example .env   # configure inter-service URLs
docker compose --profile full up -d
```

### Inter-Service Configuration

When running multiple profiles, services need to know about each other. Copy `.env.example` to `.env` and uncomment the relevant URLs:

```bash
FEATURE_SERVICE_URL=http://feature-service:8004
ML_SCORING_URL=http://ml-scoring:8005
GRAPH_SERVICE_URL=http://graph-service:8001
# OPA_URL=http://opa:8181
# OPENAI_API_KEY=sk-...
# ALLOWED_ANALYSTS=alice,bob
```

---

## Kubernetes with Helm

Helm charts are provided in `deploy/helm/fraud-stack/` (chart name: `tarka`).

### Install

```bash
helm install tarka deploy/helm/fraud-stack \
  --namespace fraud \
  --create-namespace \
  --values deploy/helm/fraud-stack/values.yaml
```

### values.yaml

The chart uses per-component toggles. Enable only what you need:

```yaml
global:
  imageRegistry: ""
  imagePullPolicy: IfNotPresent

postgres:
  enabled: true
  auth:
    username: fraud
    password: fraud       # override in production
    database: fraud

redis:
  enabled: true

decisionApi:
  enabled: true
  image: tarka-decision-api
  tag: latest
  replicaCount: 2

graphService:
  enabled: false          # set true if using graph
  image: tarka-graph-service
  tag: latest

neo4j:
  enabled: false          # required by graphService

caseApi:
  enabled: false
  image: tarka-case-api
  tag: latest

featureService:
  enabled: false
  image: tarka-feature-service
  tag: latest

mlScoring:
  enabled: false
  image: tarka-ml-scoring
  tag: latest

investigationAgent:
  enabled: false
  image: tarka-investigation-agent
  tag: latest

integrationIngress:
  enabled: false
  image: tarka-integration-ingress
  tag: latest
```

### Custom Values for Production

```bash
helm install tarka deploy/helm/fraud-stack \
  --namespace fraud \
  --create-namespace \
  --set postgres.auth.password=<strong-password> \
  --set decisionApi.replicaCount=4 \
  --set graphService.enabled=true \
  --set neo4j.enabled=true \
  --set caseApi.enabled=true \
  --set mlScoring.enabled=true
```

---

## Environment Variable Reference

### Decision API (port 8000)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://fraud:fraud@localhost:5432/fraud` | Postgres connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `RULES_PATH` | `./rules` | Path to JSON rule packs directory |
| `API_KEYS` | _(empty)_ | Comma-separated API keys (empty = no auth) |
| `DENY_THRESHOLD` | `80` | Score threshold for deny decisions |
| `REVIEW_THRESHOLD` | `50` | Score threshold for review decisions |
| `SCORE_BLEND_STRATEGY` | `average` | Score blend: `average`, `max`, `rules_only` |
| `FEATURE_SERVICE_URL` | _(empty)_ | Feature Service URL |
| `ML_SCORING_URL` | _(empty)_ | ML Scoring Service URL |
| `GRAPH_SERVICE_URL` | _(empty)_ | Graph Service URL |
| `OPA_URL` | _(empty)_ | Open Policy Agent URL |
| `ATTESTATION_NONCE_TTL` | `300` | Attestation nonce TTL in seconds |
| `ATTESTATION_HMAC_SECRET` | _(empty)_ | HMAC secret for browser attestation |
| `RATE_LIMIT_RPM` | `1000` | Rate limit (requests per minute) |

### Graph Service (port 8001)

| Variable | Default | Description |
|---|---|---|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `tarka2026` | Neo4j password (matches `deploy/docker-compose.yml` `NEO4J_AUTH`) |
| `API_KEYS` | _(empty)_ | Comma-separated API keys |

### Case API (port 8002)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://fraud:fraud@localhost:5432/fraud_cases` | Postgres connection (local default; **`deploy/docker-compose.yml` uses `…/fraud` shared with decision-api** for simplicity) |
| `GRAPH_SERVICE_URL` | _(empty)_ | Graph Service URL for case graph lookups |
| `DECISION_API_URL` | `http://localhost:8000` | Decision API base URL (dispute flows, audit fetch, etc.) |
| `ML_SCORING_URL` | _(empty)_ | Optional ML scoring service URL |
| `EVIDENCE_SIGNING_SECRET` | _(empty)_ | Optional HMAC secret for signed evidence payloads |
| `CORS_ORIGINS` | _(empty)_ | Comma-separated CORS origins |
| `WORKFLOWS_PATH` | `./workflows` | Path to workflow JSON files |
| `RATE_LIMIT_RPM` | `600` | Rate limit (requests per minute) |

### Integration Ingress (port 8003)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://fraud:fraud@localhost:5432/fraud` | Postgres connection |
| `API_KEYS` | _(empty)_ | Comma-separated API keys |

### ML Scoring (port 8005)

| Variable | Default | Description |
|---|---|---|
| `DISABLE_ML` | `false` | Disable ML scoring entirely |
| `ML_MODEL_VERSION` | `heuristic-v1` | Default model version label |
| `ONNX_MODEL_PATH` | _(empty)_ | Direct ONNX model path (legacy) |
| `MODELS_DIR` | `./models` | Model registry directory |
| `API_KEYS` | _(empty)_ | Comma-separated API keys |

### Investigation Agent (port 8006)

| Variable | Default | Description |
|---|---|---|
| `CASE_API_URL` | `http://localhost:8002` | Case API URL (cases, disputes, **investigation label drafts**) |
| `DECISION_API_URL` | `http://localhost:8000` | Decision API URL (audit, entity-velocity, **replay** for A/B tools) |
| `GRAPH_SERVICE_URL` | _(empty)_ | Graph Service URL (subgraph tools); empty disables graph tools |
| `UPSTREAM_API_KEY` | _(empty)_ | If set, sent as `x-api-key` to case-api, graph, and decision-api |
| `API_KEYS` | _(empty)_ | Comma-separated keys required on **`/v1/chat`** (empty = no auth on agent) |
| `OPENAI_API_KEY` | _(empty)_ | OpenAI API key for LLM tool-use |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible API base |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat model id |
| `ALLOWED_ANALYSTS` | `*` | Comma-separated analyst IDs (or `*` for all) |

### Event Ingest (port 8007)

| Variable | Default | Description |
|---|---|---|
| `NATS_URL` | `nats://localhost:4222` | NATS server URL |
| `DECISION_API_URL` | `http://localhost:8000` | Decision API URL for forwarding events |
| `STREAM_NAME` | `FRAUD_EVENTS` | NATS JetStream stream name |
| `SUBJECT_PREFIX` | `fraud.events` | NATS subject prefix |
| `BATCH_FLUSH_MS` | `100` | Batch flush interval in ms |
| `MAX_BATCH_SIZE` | `256` | Maximum events per batch pull |
| `API_KEYS` | _(empty)_ | Comma-separated API keys |

### Analytics Sink (port 8008)

| Variable | Default | Description |
|---|---|---|
| `CLICKHOUSE_HOST` | `localhost` | ClickHouse host |
| `NATS_URL` | `nats://localhost:4222` | NATS server URL |

### Infrastructure

| Component | Key Environment Variables |
|---|---|
| **Postgres** | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` |
| **Neo4j** | `NEO4J_AUTH` (format: `user/password`) |
| **OPA** | Policy files mounted at `/policies/` |

---

## Scaling Considerations

### Decision API

The Decision API is the most latency-sensitive service. Scale horizontally behind a load balancer.

- **CPU-bound:** Rule evaluation and score blending are pure computation.
- **IO-bound:** Redis lookups, ML scoring HTTP call, graph upserts (background).
- **Recommendation:** 2–4 replicas per 1,000 RPS. Each replica handles ~500 RPS with p99 < 50ms.

### Redis

- Use Redis Cluster for > 100k tags or high aggregate throughput.
- Sorted sets for aggregates grow linearly with event volume. The 30-day max window and TTL keep data bounded.

### Observability (Prometheus / Grafana)

- Optional **compose merge** stacks Prometheus + Grafana against Tarka **`/metrics`** endpoints: [deploy/observability/README.md](../../../deploy/observability/README.md).

### Postgres

- Decision API and Case API can share a Postgres instance but use separate databases.
- **Schema migrations:** both services ship **Alembic** (`services/decision-api/alembic/`, `services/case-api/alembic/`). On startup, **PostgreSQL** URLs run `alembic upgrade head` automatically; **SQLite** (tests / local quick runs) still uses `create_all`. For manual upgrades: `cd services/decision-api && DATABASE_URL=postgresql+psycopg://… alembic upgrade head` (and the same for `case-api` with its `DATABASE_URL`). If you already created tables with `create_all` and the schema matches the initial revision, run **`alembic stamp head`** once instead of `upgrade` to avoid “already exists” errors.
- Audit records grow linearly with traffic. Implement a retention policy (e.g., archive records older than 90 days).
- Add read replicas for Case API list queries under high load.

### Neo4j

- Neo4j Community Edition is single-instance. For production HA, consider Neo4j Enterprise or the JanusGraph adapter.
- Graph size grows with unique entities. Typical deployment: ~10M nodes, ~50M relationships handles well on a single instance with 16GB RAM.

### NATS JetStream

- Default configuration stores up to 10M messages or 1GB, with 7-day retention.
- Scale by adding more consumer instances (each pulls from the durable subscription).

### ClickHouse

- Highly efficient at ingesting append-only event data.
- For multi-terabyte datasets, use ClickHouse's distributed table engine across multiple shards.

---

## Security Hardening Checklist

### Authentication

- [ ] Set `API_KEYS` on all services with strong, unique keys
- [ ] Rotate API keys on a regular schedule
- [ ] Use separate API keys for each client application

### Network

- [ ] Do not expose infrastructure ports (5432, 6379, 7687, 4222) externally
- [ ] Use an ingress controller / API gateway in front of service ports
- [ ] Enable TLS on all external-facing endpoints
- [ ] Configure `CORS_ORIGINS` on Case API to restrict allowed origins

### Database

- [ ] Change default Postgres password (`fraud:fraud`) to a strong password
- [ ] Change default Neo4j password (compose default `neo4j/tarka2026`) to a strong password
- [ ] Enable Postgres SSL connections in production
- [ ] Implement database backup and recovery procedures

### Secrets

- [ ] Store `OPENAI_API_KEY` in a secrets manager (Vault, AWS Secrets Manager, K8s secrets)
- [ ] Store `ATTESTATION_HMAC_SECRET` in a secrets manager
- [ ] Never commit `.env` files to version control

### Monitoring

- [ ] All services expose `/v1/health` — configure liveness probes
- [ ] Prometheus metrics are available via the observability module
- [ ] Set up alerts for high error rates and latency spikes
- [ ] Monitor NATS consumer lag for the event ingest pipeline

### Data

- [ ] Implement audit record retention policies
- [ ] Configure Redis `maxmemory` and eviction policies
- [ ] Back up Neo4j data volumes regularly
- [ ] Encrypt data at rest for Postgres and ClickHouse volumes

### Rate Limiting

- [ ] Configure `RATE_LIMIT_RPM` appropriate to your traffic volume
- [ ] Implement additional rate limiting at the ingress/API gateway level
- [ ] Monitor for rate limit violations in service logs
