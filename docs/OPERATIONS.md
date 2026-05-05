# Operations guide

How to **deploy**, **scale**, and **recover** Tarka in real environments. Deep product-specific guides live under [`docs/guides/`](docs/guides/) (Kubernetes, cloud bundles, security rollout); this page is the operator’s map.

---

## 1. Deployment paths

| Path | When to use | Entry points |
|------|-------------|----------------|
| **Tarka Micro** | Laptop / CI smoke; single API process, file-backed state | [`deploy/docker-compose.micro.yml`](../deploy/docker-compose.micro.yml), [`scripts/start-micro.sh`](../scripts/start-micro.sh) |
| **Lite stack** | “Five minutes” full-ish demo: Postgres, Redis, NATS, core, signal, ingress, optional graph | [`deploy/docker-compose.lite.yml`](../deploy/docker-compose.lite.yml) |
| **Full Compose** | Modular production-like stack via profiles (`core`, `graph`, `streaming`, …) | [`deploy/docker-compose.yml`](../deploy/docker-compose.yml), [Deployment guide](docs/guides/deployment.md) |
| **Kubernetes / Helm** | Managed clusters, multi-tenant isolation | [`deploy/helm/`](../deploy/helm/), [Cloud presets](docs/guides/deployment-presets.md) |
| **CLI installer** | Local dev without hand-editing Compose | [`tarka.py`](../tarka.py) — `install`, `start`, `logs`, `status` |

**First-time checklist**

1. Copy and edit environment: start from [`deploy/.env.example`](../deploy/.env.example) (or profile-specific docs).
2. **Secrets**: API keys, DB passwords, OSINT vendor keys, FinCEN SFTP (if used) — never commit; use vault or CI secrets.
3. **Migrations**: `core-api` and standalone services run **Alembic** on startup or via one-shot jobs (see each service’s Dockerfile `CMD` / Helm hooks).
4. **Rust rule engine**: `core-api` / `decision-api` images build `tarka_rule_engine` with **maturin**; local dev: `cd services/rule-engine && maturin develop --release` (see [README](../README.md)).

---

## 2. Scaling

### Stateless APIs (horizontal)

- **decision-api** (standalone or mounted in **core-api**), **case-api**, **graph-service**, **integration-ingress**, **signal-api**: scale **replica count** behind a load balancer. Keep **sticky sessions off** unless a specific feature requires them (default: stateless).
- Configure **per-process concurrency** (Uvicorn workers / `--workers`) according to CPU; prefer more **small** processes over one huge process for tail latency.

### Data plane & messaging

- **Postgres**: primary + read replicas for reporting only; **writes** go to the primary. Size connections with pool limits per service (`DATABASE_URL` / SQLAlchemy pools).
- **Redis**: use a managed cluster or Redis Sentinel for HA; tune memory and eviction for feature-store / aggregate keys.
- **NATS JetStream**: cluster for HA; persist volumes for JetStream store; align `NATS_URL` across **decision-api**, **integration-ingress**, and ingest workers.
- **ClickHouse** (analytics profile): separate read scaling from write path; keep **bounded query timeouts** (see decision-api / analytics config).

### Graph

- Default path is **Gremlin Server** (JanusGraph-compatible) — see [`services/graph-service/docs/janusgraph-adapter.md`](../services/graph-service/docs/janusgraph-adapter.md). Scale graph workloads by **query complexity limits** and **replica graph stores**, not by piling synchronous graph work into the evaluate hot path.

### Rate and cost controls

- Use **evaluation step timeouts** and circuit settings (see [Evaluation step controls](docs/guides/evaluation-step-controls.md)).
- OSINT is **async** on the evaluate path; workers scale independently of API replicas.

---

## 3. Recovery & runbooks

### Health and readiness

- **Core / platform**: `GET /v1/health` on the gateway or core bundle.
- **Decision API**: `GET …/decisions/v1/health` or `…/v1/ready` (as wired in Compose).
- **Case API**: `GET …/cases/v1/health`.
- Treat **503** with `reason_code` as first-class signals for dependency outage (see [README](../README.md) fail-closed example).

### Order of restart (typical)

1. **Postgres** → **Redis** → **NATS** (foundations).  
2. **signal-api** (features / ML upstream for core).  
3. **core-api** or **decision-api** + **case-api**.  
4. **integration-ingress** (OSINT worker + screening).  
5. **graph-service** (if profile enabled).  
6. **Frontend** / edge last.

### Postgres failure

- **RTO/RPO** are your policy; Tarka expects a **durable** Postgres for audit and case state.
- Restore from backup; re-run **Alembic** if restoring to a fresh volume (`upgrade head`).
- If replication lagged, reconcile **idempotent** consumers (NATS) and any **outbox** patterns you added outside this repo.

### Redis loss

- **Non-authoritative** caches (features, async OSINT materialization) may be rebuilt; evaluate may **degrade** (tags / scores) until caches warm. Audit rows in Postgres remain source of truth for what was decided **if** decision logging was enabled.

### Partial dependency outage

- Circuits open → **degraded** evaluate with documented tags / `fallback_reason`; monitor Prometheus-style counters if exported.
- Restore upstream (ClickHouse, ML URL, OPA URL, etc.), then **fail a few canary requests** before declaring green.

### Bad deploy / rollback

1. Pin previous image digest in Compose / Helm values.  
2. **Roll back** deployment; run **down** migrations only if Alembic downgrade is supported and tested (often **forward-fix** is safer).  
3. Re-verify **rule pack** version and **Rust engine** sync after rollback.

### Chaos and CI smoke

- Automated resilience checks: [`.github/workflows/chaos-smoke.yml`](../.github/workflows/chaos-smoke.yml), counter parity and benchmark smokes in `.github/workflows/`.

---

## 4. Observability & support

- **Logs**: `python tarka.py logs -f` for local bundles; in K8s use cluster logging (JSON logs from Uvicorn / structlog where configured).
- **Security scanning**: Trivy + TruffleHog in GitHub Actions (see [`.github/workflows/security-scan.yml`](../.github/workflows/security-scan.yml), [`secret-scan.yml`](../.github/workflows/secret-scan.yml)).
- **Integrity / honesty status**: [`docs/INTEGRITY.md`](INTEGRITY.md) and the [Tier-1 Honesty Program](TIER_1_HONESTY_PROGRAM.md).

For procurement-grade checklists (tenant binding, API keys, idempotency), use **[Production security rollout](docs/guides/production-security-rollout.md)**.
