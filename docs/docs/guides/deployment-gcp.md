# Deploying Tarka on GCP

This guide maps Tarka deployment artifacts ([Docker Compose](../../../deploy/docker-compose.yml), [Helm chart](../../../deploy/helm/fraud-stack/)) to a practical Google Cloud production layout.

It is intentionally parallel to AWS guidance so operators can follow the same mental model across clouds.

**See also:** [Deployment Guide](./deployment.md), [Deploying on AWS](./deployment-aws.md), [Cloud presets and generated values](./deployment-presets.md), [Cloud-native deployment bundles](./deployment-cloud-native-bundles.md), [Managed services and secrets contract](./deployment-managed-services.md).

---

## Recommended shape

| Concern | GCP service (typical) | Notes |
|---|---|---|
| Kubernetes runtime | GKE | Primary production runtime for modular Tarka bundles |
| Ingress and TLS | GKE Ingress + Google Cloud Load Balancing + Certificate Manager | Expose frontend, GraphQL, and APIs with managed certificates |
| Container images | Artifact Registry | Build from `services/*/Dockerfile` and publish immutable tags |
| Relational DB | Cloud SQL for PostgreSQL | Shared or isolated DB instances for decision and case workloads |
| Cache | Memorystore for Redis | Use private networking and AUTH/TLS where supported |
| Graph | Neo4j Aura or self-managed graph on GKE | Plan capacity, backups, and upgrade windows |
| Streaming | NATS (GKE) or managed equivalent by policy | Keep stream retention and lag visibility explicit |
| Analytics | ClickHouse on GKE or managed ClickHouse offering | Size for ingest and query concurrency requirements |
| Secrets | Secret Manager + External Secrets | Inject app/runtime secrets without editing manifests |
| Workload identity | Workload Identity Federation | Avoid long-lived service account keys in workloads |

---

## Helm with managed services

For production GCP environments, prefer managed services over chart-managed Postgres/Redis/etc:

1. Disable chart-managed infra (`postgres.enabled=false`, `redis.enabled=false`, etc.).
2. Enable `global.externalServices.*`.
3. Pass managed endpoints via values generated from your environment.

Example (`core` bundle):

```yaml
postgres:
  enabled: false
redis:
  enabled: false

global:
  externalServices:
    postgres:
      enabled: true
      databaseUrl: postgresql+asyncpg://fraud:${DB_PASSWORD}@10.40.0.5:5432/fraud
    redis:
      enabled: true
      redisUrl: redis://10.50.0.8:6379/0
```

---

## GCP checklist

- [ ] GKE cluster with Workload Identity configured
- [ ] Artifact Registry repos created for each enabled service
- [ ] Cloud SQL and Memorystore provisioned with private networking
- [ ] Secret Manager entries for all Tarka runtime secrets
- [ ] Helm values generated from a supported preset
- [ ] Ingress hosts, TLS certificates, and DNS wired
- [ ] Health checks and metrics dashboards configured before go-live

---

## Suggested rollout path

1. Start with `core-on-gcp` preset for fastest secure baseline.
2. Add `investigation` modules after case-management integrations are verified.
3. Introduce streaming and analytics once throughput and retention requirements are clear.
4. Move to `full` only if teams need all modules in one cluster.
