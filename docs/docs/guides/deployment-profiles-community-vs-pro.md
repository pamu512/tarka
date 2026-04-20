# Deployment profiles: **Community** vs **Pro**

**Purpose:** Map Tarka’s runnable stacks to two operational tiers—**Community** (minimal footprint, fast onboarding) and **Pro** (full modular stack)—with copy-paste Compose commands, env fragments, and known limits. Aligns with GitHub **#38** (integration-ingress / platform swimlane).

**Sources in repo:** `deploy/docker-compose.lite.yml` (community-shaped), `deploy/docker-compose.yml` + Compose **profiles** (pro modular), `deploy/.env.example` (pro-oriented defaults).

---

## At a glance

| Dimension | **Community** | **Pro** |
|-----------|---------------|---------|
| **Primary compose file** | `deploy/docker-compose.lite.yml` | `deploy/docker-compose.yml` |
| **Database** | Postgres 16 | Postgres 16 |
| **Cache** | Redis 7 | Redis 7 |
| **Message bus** | — (not in lite file) | NATS JetStream (`--profile streaming` or `full`) |
| **Graph** | Disabled in lite (empty `GRAPH_SERVICE_URL`) | Neo4j + graph-service (`--profile graph` or `full`) |
| **ML** | Disabled in lite | feature-service + ml-scoring (`--profile ml` or `full`) |
| **Event ingest + idempotency** | Not in lite compose | event-ingest + Redis (`--profile streaming` / `full`) |
| **Analytics** | Not in lite | ClickHouse + analytics-sink (`--profile analytics` / `full`) |
| **Investigation agent / UI** | Optional frontend in lite | `--profile agent`, `--profile ui` or `full` |
| **Horizontal scale** | Single-node laptop compose only | Still compose-bound; use **Kubernetes/Helm** for HA |
| **Typical use** | Demos, CI smoke, laptop eval | Team dev, staging, prod-like integration |

---

## Community — copy / paste

From repository root:

```bash
docker compose -f deploy/docker-compose.lite.yml up --build -d
```

**Services (lite file):** Postgres, Redis, decision-api, case-api, integration-ingress, frontend (see file for exact list and ports).

**Env:** use `deploy/env/community.env.example` as a starting point (copy beside the compose file or merge into your shell / CI secrets). Lite compose sets empty optional URLs for graph/ML/OPA so the Decision API does not block on missing deps.

**Limitations:**

- No Neo4j / graph enrichment paths unless you add services yourself.
- No NATS / event-ingest in this file → no JetStream fan-out from this stack definition.
- Not a substitute for load testing or HA; volumes are local Docker volumes.

---

## Pro — copy / paste

**Minimal “core” fraud plane** (Decision API + DB + cache):

```bash
cd deploy
docker compose --profile core up -d --build
```

**Full modular stack** (all services in `docker-compose.yml` that belong to `full`):

```bash
cd deploy
cp .env.example .env   # edit URLs and secrets
docker compose --profile full up -d --build
```

**Custom slices** (examples):

```bash
docker compose --profile core --profile graph --profile cases up -d
docker compose --profile core --profile ml --profile integration up -d
```

**Env:** start from `deploy/.env.example` (full inter-service URL matrix). For a slimmer `.env` when only **core + cases** is running, see `deploy/env/pro-core-cases.env.example`.

**Limitations:**

- `full` pulls many images and ports; reserve ports per [service-ports.md](./service-ports.md).
- Production still needs secrets management, backups, network policy, and observability—see [deployment.md](./deployment.md) and [docker-compose.production-hardening.yml](../../../deploy/docker-compose.production-hardening.yml).

---

## Environment matrix (reference)

| Variable / concern | Community (lite) | Pro (modular compose) |
|--------------------|------------------|------------------------|
| `DATABASE_URL` | Postgres service | Postgres service |
| `REDIS_URL` | Redis service | Redis service |
| `NATS_URL` | N/A in lite file | `nats://nats:4222` when streaming profile |
| `GRAPH_SERVICE_URL` | `""` in lite | Set when graph profile on |
| `FEATURE_SERVICE_URL` / `ML_SCORING_URL` | `""` in lite | Set when ml profile on |
| `CLICKHOUSE_*` / analytics | N/A in lite | With analytics profile |
| Idempotent ingest | N/A in lite compose | event-ingest + `REDIS_URL` (see [ingest-replay-onboarding.md](./ingest-replay-onboarding.md)) |

---

## CI / smoke

- Full-repo smoke: GitHub Actions **`stack-smoke`** runs `scripts/ci/full_stack_smoke.py` (health + evaluate)—see root CI workflow.
- **Optional:** run the same script locally against **Community** (`lite`) or **Pro** (`core` / `full`) after `docker compose up` to validate both tiers when changing compose or env docs.

### Tenant reliability profile (Decision API)

Set **`TARKA_TENANT_RELIABILITY_PROFILE`** on **decision-api** to one of **`strict`**, **`balanced`** (default), or **`permissive`**. Invalid or empty values fall back to **`balanced`**. The active value is returned as **`tenant_reliability_profile`** on **`GET /v1/ops/evaluation-posture`** (analyst workspace strip and automation can read the same field).

---

## Module swimlane

**Integration / platform** — GitHub **#38** (`borrowed-from-OSS`). For compose overlays beyond this page, see also [deployment.md](./deployment.md) and `deploy/docker-compose.sandbox.yml` for sandbox-specific tweaks.
