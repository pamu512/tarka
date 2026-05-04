# Deployment Guide

This guide covers deploying Tarka from local development through production, including Docker Compose profiles, Kubernetes with Helm, environment variable reference, scaling, and security hardening.

**Public cloud (Kubernetes):** For AWS, Azure, and GCP service mapping, ingress, managed Postgres/Redis, and secrets patterns, see **[Deploying on AWS](./deployment-aws.md)**, **[Deploying on Azure](./deployment-azure.md)**, and **[Deploying on GCP](./deployment-gcp.md)**.

**Cloud bundle model:** Use **[Cloud-native deployment bundles](./deployment-cloud-native-bundles.md)** to choose `core`, `investigation`, `streaming`, `analytics`, or `full` by outcome.

**Preset workflows:** Use **[Cloud presets and generated values](./deployment-presets.md)** for low-touch AWS/GCP onboarding.

**Managed dependency mode:** Use **[Managed services and secrets contract](./deployment-managed-services.md)** when customer-owned cloud infrastructure is the system of record.

**Lighter adoption path:** Use **[Lighter managed-container deployment path](./deployment-lighter-runtime.md)** when teams need partial Tarka adoption before Kubernetes.

**Release gate:** Use **[Cloud release readiness](./deployment-release-readiness.md)** before promoting cloud environments.

**Security hardening rollout:** Use **[Production security rollout checklist](./production-security-rollout.md)** for staged cutover of tenant binding, API keys, Copilot trusted headers, ingest/evaluate idempotency, WebSockets, and rollback toggles.

**See also:** [Service ports & OpenAPI index](./service-ports.md) — default ports, Compose DNS names, and contract file mapping.

**Runtime tiers:** [Deployment profiles — Community vs Pro](./deployment-profiles-community-vs-pro.md) — `docker-compose.lite.yml` vs profile-based `docker-compose.yml`, env matrix, limitations (**#38**).

**Evaluate path hardening:** [Evaluation step controls](./evaluation-step-controls.md) — optional-service timeouts and retries (**#32**).

---

## Docker Compose Profiles

The `deploy/docker-compose.yml` file uses Compose profiles so you can pick exactly the components you need.

### Available Profiles


| Profile       | Services Included                                                                 |
| ------------- | ---------------------------------------------------------------------------------- |
| `core`        | **Core API** (decisions + cases), **Signal API**, Postgres, Redis                   |
| `graph`       | Graph Service, Neo4j                                                              |
| `ml`          | Triton (ONNX); **Signal API** is already included with `core`                      |
| `streaming`   | **Data plane** ingest path, NATS JetStream                                        |
| `analytics`   | **Data plane** analytics path, ClickHouse                                          |
| `integration` | Integration Ingress                                                               |
| `agent`       | Investigation Agent (embedded **chat_bridge** for Slack / Teams / Lark)          |
| `gateway`     | GraphQL Gateway                                                                   |
| `opa`         | Open Policy Agent                                                                 |
| `risk`        | Same **Signal API** image profile hook for counter/location-heavy demos (optional) |
| `full`        | All of the above                                                                  |


### Usage Examples

**Core only** — minimum viable fraud scoring:

```bash
cd deploy
docker compose --profile core up -d
```

**Core + graph** — scoring with graph analytics (cases live on **core-api** at `/cases`):

```bash
docker compose --profile core --profile graph up -d
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

**Collaboration chat (Slack / Teams / Lark)** — enable **`agent`**; the **chat_bridge** runs **inside investigation-agent** on **`/v1/chat/…`**. Use **`core`** (and **`graph`** if you need graph-backed tools). Operator wiring and secrets: **[Collaboration chat & cloud](./investigation-collaboration-chat-aws-azure.md)**.

### Inter-Service Configuration

When running multiple profiles, services need to know about each other. Copy `.env.example` to `.env` and uncomment the relevant URLs:

```bash
# Defaults in compose already point core-api at signal-api mounts:
# FEATURE_SERVICE_URL=http://signal-api:8004/features
# ML_SCORING_URL=http://signal-api:8004/ml
# CALIBRATION_SERVICE_URL=http://signal-api:8004/calibration
# COUNTER_SERVICE_URL=http://signal-api:8004/counters
# LOCATION_SERVICE_URL=http://signal-api:8004/location
GRAPH_SERVICE_URL=http://graph-service:8001
# UPSTREAM_API_KEY=<optional-shared-service-key>
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
  externalServices:
    postgres:
      enabled: false
      databaseUrl: ""
    redis:
      enabled: false
      redisUrl: ""
    neo4j:
      enabled: false
      uri: ""
      user: "neo4j"
      password: ""
    nats:
      enabled: false
      url: ""
    clickhouse:
      enabled: false
      host: ""
      port: 8123
      user: "default"
      password: ""
      database: "fraud"

postgres:
  enabled: true
  auth:
    username: fraud
    password: fraud       # override in production
    database: fraud

redis:
  enabled: true

coreApi:
  enabled: true
  image: tarka-core-api
  tag: latest
  replicaCount: 2
  podDisruptionBudget:
    enabled: true
    minAvailable: 1
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 8
    targetCPUUtilizationPercentage: 70

signalApi:
  enabled: false
  image: tarka-signal-api
  tag: latest

graphService:
  enabled: false          # set true if using graph
  image: tarka-graph-service
  tag: latest

neo4j:
  enabled: false          # required by graphService

investigationAgent:
  enabled: false
  image: tarka-investigation-agent
  tag: latest

opa:
  enabled: false
  image: openpolicyagent/opa:0.70.0

integrationIngress:
  enabled: false
  image: tarka-integration-ingress
  tag: latest
```

### Managed services mode (RDS / ElastiCache / managed graph or analytics)

When customers already run cloud-native data infrastructure, keep chart-managed dependencies disabled and inject managed endpoints through `global.externalServices.*`.

Example:

```yaml
postgres:
  enabled: false
redis:
  enabled: false
neo4j:
  enabled: false
nats:
  enabled: false
clickhouse:
  enabled: false

global:
  externalServices:
    postgres:
      enabled: true
      databaseUrl: postgresql+asyncpg://fraud:${DB_PASSWORD}@my-rds.cluster.amazonaws.com:5432/fraud
    redis:
      enabled: true
      redisUrl: rediss://my-elasticache.cache.amazonaws.com:6379/0
    nats:
      enabled: true
      url: nats://nats.mycompany.internal:4222
```

### Custom Values for Production

```bash
helm install tarka deploy/helm/fraud-stack \
  --namespace fraud \
  --create-namespace \
  --set postgres.auth.password=<strong-password> \
  --set coreApi.replicaCount=4 \
  --set graphService.enabled=true \
  --set neo4j.enabled=true \
  --set signalApi.enabled=true
```

---

## Environment Variable Reference

In **Docker Compose** and **Helm** defaults, the Decision and Case FastAPI apps run inside **core-api** on port **8000** with path prefixes **`/decisions`** and **`/cases`**. The tables below describe the **decision-api** and **case-api** Python modules (same env vars when mounted or when run standalone for development).

### Decision API (port 8000, or `/decisions` on core-api)


| Variable                  | Default                                                 | Description                                                       |
| ------------------------- | ------------------------------------------------------- | ----------------------------------------------------------------- |
| `DATABASE_URL`            | `postgresql+asyncpg://fraud:fraud@localhost:5432/fraud` | Postgres connection                                               |
| `REDIS_URL`               | `redis://localhost:6379/0`                              | Redis connection                                                  |
| `RULES_PATH`              | `./rules`                                               | Path to JSON rule packs directory                                 |
| `API_KEYS`                | *(empty)*                                               | Comma-separated API keys (empty = no auth)                        |
| `DENY_THRESHOLD`          | `80`                                                    | Score threshold for deny decisions                                |
| `REVIEW_THRESHOLD`        | `50`                                                    | Score threshold for review decisions                              |
| `SCORE_BLEND_STRATEGY`    | `average`                                               | Score blend: `average`, `max`, `rules_only`                       |
| `FEATURE_SERVICE_URL`     | *(empty)*                                               | Feature Service URL                                               |
| `ML_SCORING_URL`          | *(empty)*                                               | ML Scoring Service URL                                            |
| `GRAPH_SERVICE_URL`       | *(empty)*                                               | Graph Service URL                                                 |
| `CALIBRATION_SERVICE_URL` | *(empty)*                                               | Calibration Service URL (`/v1/score`, `/v1/drift`)                |
| `COUNTER_SERVICE_URL`     | *(empty)*                                               | Counter Service URL (`/v1/record-and-query`)                      |
| `LOCATION_SERVICE_URL`    | *(empty)*                                               | Location Service URL (`/v1/evaluate`)                             |
| `UPSTREAM_API_KEY`        | *(empty)*                                               | API key forwarded by decision-api to downstream services when set |
| `OPA_URL`                 | *(empty)*                                               | Open Policy Agent URL                                             |
| `ATTESTATION_NONCE_TTL`   | `300`                                                   | Attestation nonce TTL in seconds                                  |
| `ATTESTATION_HMAC_SECRET` | *(empty)*                                               | HMAC secret for browser attestation                               |
| `RATE_LIMIT_RPM`          | `1000`                                                  | Rate limit (requests per minute)                                  |


### Graph Service (port 8001)


| Variable         | Default                 | Description                                                       |
| ---------------- | ----------------------- | ----------------------------------------------------------------- |
| `NEO4J_URI`      | `bolt://localhost:7687` | Neo4j Bolt URI                                                    |
| `NEO4J_USER`     | `neo4j`                 | Neo4j username                                                    |
| `NEO4J_PASSWORD` | `tarka2026`             | Neo4j password (matches `deploy/docker-compose.yml` `NEO4J_AUTH`) |
| `API_KEYS`       | *(empty)*               | Comma-separated API keys                                          |


### Case API (port 8002, or `/cases` on core-api)


| Variable                  | Default                                                       | Description                                                                                                                 |
| ------------------------- | ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`            | `postgresql+asyncpg://fraud:fraud@localhost:5432/fraud_cases` | Postgres connection (local default; `**deploy/docker-compose.yml` uses `…/fraud` shared with decision-api** for simplicity) |
| `GRAPH_SERVICE_URL`       | *(empty)*                                                     | Graph Service URL for case graph lookups                                                                                    |
| `DECISION_API_URL`        | `http://localhost:8000/decisions`                               | Decision API base URL including **`/decisions`** mount when using core-api (dispute flows, audit fetch, etc.)                |
| `ML_SCORING_URL`          | *(empty)*                                                     | Optional ML scoring service URL                                                                                             |
| `EVIDENCE_SIGNING_SECRET` | *(empty)*                                                     | Optional HMAC secret for signed evidence payloads                                                                           |
| `CORS_ORIGINS`            | *(empty)*                                                     | Comma-separated CORS origins                                                                                                |
| `WORKFLOWS_PATH`          | `./workflows`                                                 | Path to workflow JSON files                                                                                                 |
| `RATE_LIMIT_RPM`          | `600`                                                         | Rate limit (requests per minute)                                                                                            |


### Integration Ingress (port 8003)


| Variable       | Default                                                 | Description              |
| -------------- | ------------------------------------------------------- | ------------------------ |
| `DATABASE_URL` | `postgresql+asyncpg://fraud:fraud@localhost:5432/fraud` | Postgres connection      |
| `API_KEYS`     | *(empty)*                                               | Comma-separated API keys |


### ML Scoring (port 8005)


| Variable           | Default        | Description                     |
| ------------------ | -------------- | ------------------------------- |
| `DISABLE_ML`       | `false`        | Disable ML scoring entirely     |
| `ML_MODEL_VERSION` | `heuristic-v1` | Default model version label     |
| `ONNX_MODEL_PATH`  | *(empty)*      | Direct ONNX model path (legacy) |
| `MODELS_DIR`       | `./models`     | Model registry directory        |
| `API_KEYS`         | *(empty)*      | Comma-separated API keys        |


### Investigation Agent (port 8006)


| Variable            | Default                     | Description                                                                |
| ------------------- | --------------------------- | -------------------------------------------------------------------------- |
| `CASE_API_URL`      | `http://localhost:8000/cases` | Case API URL including **`/cases`** mount when using core-api (cases, disputes, **investigation label drafts**) |
| `DECISION_API_URL`  | `http://localhost:8000/decisions` | Decision API URL including **`/decisions`** mount (audit, entity-velocity, **replay** for A/B tools)        |
| `GRAPH_SERVICE_URL` | *(empty)*                   | Graph Service URL (subgraph tools); empty disables graph tools             |
| `UPSTREAM_API_KEY`  | *(empty)*                   | If set, sent as `x-api-key` to case-api, graph, and decision-api           |
| `API_KEYS`          | *(empty)*                   | Comma-separated keys required on `**/v1/chat*`* (empty = no auth on agent) |
| `OPENAI_API_KEY`    | *(empty)*                   | OpenAI API key for LLM tool-use                                            |
| `OPENAI_BASE_URL`   | `https://api.openai.com/v1` | OpenAI-compatible API base                                                 |
| `OPENAI_MODEL`      | `gpt-4o-mini`               | Chat model id                                                              |
| `ALLOWED_ANALYSTS`  | `*`                         | Comma-separated analyst IDs (or `*` for all)                               |


### Collaboration chat bridge (port 8009)


| Variable                      | Default                           | Description                                                                             |
| ----------------------------- | --------------------------------- | --------------------------------------------------------------------------------------- |
| `INVESTIGATION_AGENT_URL`     | `http://investigation-agent:8006` | Investigation agent base URL (no trailing slash)                                        |
| `INVESTIGATION_AGENT_API_KEY` | *(empty)*                         | If set, sent as `x-api-key` to the agent                                                |
| `SLACK_SIGNING_SECRET`        | *(empty)*                         | Slack Events API signing secret                                                         |
| `SLACK_BOT_TOKEN`             | *(empty)*                         | Slack bot token (`xoxb-…`) for replies / thread reads                                   |
| `TEAMS_BRIDGE_SECRET`         | *(empty)*                         | Shared secret for Teams/custom connector posts (`X-Bridge-Secret`)                      |
| `BRIDGE_PLUGIN_SECRET`        | *(empty)*                         | Secret for bridge-proxied `/v1/plugin/`* (falls back to `TEAMS_BRIDGE_SECRET` if empty) |
| `LARK_VERIFICATION_TOKEN`     | *(empty)*                         | Lark / Feishu verification token                                                        |
| `LARK_TENANT_ACCESS_TOKEN`    | *(empty)*                         | Lark tenant token for outbound messages                                                 |


Full ingress options, rate limits, and cloud runbooks: **[Collaboration chat & cloud](./investigation-collaboration-chat-aws-azure.md)**.

### Event Ingest (port 8007)


| Variable           | Default                 | Description                            |
| ------------------ | ----------------------- | -------------------------------------- |
| `NATS_URL`         | `nats://localhost:4222` | NATS server URL                        |
| `DECISION_API_URL` | `http://localhost:8000` | Decision API URL for forwarding events |
| `STREAM_NAME`      | `FRAUD_EVENTS`          | NATS JetStream stream name             |
| `SUBJECT_PREFIX`   | `fraud.events`          | NATS subject prefix                    |
| `BATCH_FLUSH_MS`   | `100`                   | Batch flush interval in ms             |
| `MAX_BATCH_SIZE`   | `256`                   | Maximum events per batch pull          |
| `API_KEYS`         | *(empty)*               | Comma-separated API keys               |


### Analytics Sink (port 8008)


| Variable          | Default                 | Description     |
| ----------------- | ----------------------- | --------------- |
| `CLICKHOUSE_HOST` | `localhost`             | ClickHouse host |
| `NATS_URL`        | `nats://localhost:4222` | NATS server URL |


### Infrastructure


| Component    | Key Environment Variables                           |
| ------------ | --------------------------------------------------- |
| **Postgres** | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` |
| **Neo4j**    | `NEO4J_AUTH` (format: `user/password`)              |
| **OPA**      | Policy files mounted at `/policies/`                |


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

- Optional **compose merge** stacks Prometheus + Grafana against Tarka `**/metrics*`* endpoints: [deploy/observability/README.md](../../../deploy/observability/README.md).

### Postgres

- Decision API and Case API can share a Postgres instance but use separate databases.
- **Schema migrations:** both services ship **Alembic** (`services/decision-api/alembic/`, `services/case-api/alembic/`). On startup, **PostgreSQL** URLs run `alembic upgrade head` automatically; **SQLite** (tests / local quick runs) still uses `create_all`. For manual upgrades: `cd services/decision-api && DATABASE_URL=postgresql+psycopg://… alembic upgrade head` (and the same for `case-api` with its `DATABASE_URL`). If you already created tables with `create_all` and the schema matches the initial revision, run `**alembic stamp head`** once instead of `upgrade` to avoid “already exists” errors.
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

- Set `API_KEYS` on all services with strong, unique keys
- Rotate API keys on a regular schedule
- Use separate API keys for each client application

### Network

- Do not expose infrastructure ports (5432, 6379, 7687, 4222) externally
- Use an ingress controller / API gateway in front of service ports
- Enable TLS on all external-facing endpoints
- Configure `CORS_ORIGINS` on Case API to restrict allowed origins

### Database

- Change default Postgres password (`fraud:fraud`) to a strong password
- Change default Neo4j password (compose default `neo4j/tarka2026`) to a strong password
- Enable Postgres SSL connections in production
- Implement database backup and recovery procedures

### Secrets

- Store `OPENAI_API_KEY` in a secrets manager (Vault, AWS Secrets Manager, K8s secrets)
- Store `ATTESTATION_HMAC_SECRET` in a secrets manager
- Never commit `.env` files to version control

### Monitoring

- All services expose `/v1/health` — configure liveness probes
- Prometheus metrics are available via the observability module
- Set up alerts for high error rates and latency spikes
- Monitor NATS consumer lag for the event ingest pipeline

### Data

- Implement audit record retention policies
- Configure Redis `maxmemory` and eviction policies
- Back up Neo4j data volumes regularly
- Encrypt data at rest for Postgres and ClickHouse volumes

### Rate Limiting

- Configure `RATE_LIMIT_RPM` appropriate to your traffic volume
- Implement additional rate limiting at the ingress/API gateway level
- Monitor for rate limit violations in service logs

