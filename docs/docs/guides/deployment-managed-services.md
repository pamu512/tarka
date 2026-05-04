# Managed services and secrets contract

This guide describes how to run Tarka against customer-managed cloud infrastructure instead of chart-managed databases and queues.

Use this for AWS, GCP, or any environment where platform teams already own data stores, IAM, secret rotation, and network controls.

When rolling out **secret-backed auth and tenant controls** after wiring `global.appSecretsName` and shared keys, use **[Production security rollout checklist](./production-security-rollout.md)** for ordering, compatibility toggles, and rollback.

---

## Runtime classification

| Class | Services | Cloud-native expectation |
|---|---|---|
| Stateless HTTP services | `decision-api`, `case-api`, `integration-ingress`, `feature-service`, `ml-scoring`, `graphql-gateway`, `frontend`, `event-ingest`, `analytics-sink` | Horizontal scale behind ingress; no local persistent volumes required |
| Stateful infrastructure dependencies | Postgres, Redis, Neo4j, NATS, ClickHouse | Prefer managed services and inject endpoints via Helm values/secrets |
| Local-disk/embedded state (needs architecture decision before elastic scale) | `investigation-agent` local SQLite stores; optional external **calibration** if you run one; `location-service` `/data` | Externalize storage (DB/object store) or document single-writer limits before aggressive autoscaling |

---

## Managed dependency contract

When using managed infrastructure:

1. Disable chart-managed infra (`postgres.enabled=false`, `redis.enabled=false`, etc.).
2. Set `global.externalServices.*.enabled=true`.
3. Provide managed endpoints and credentials through secret-backed values.
4. Keep application images and runtime manifests unchanged.

---

## Secrets contract

### Shared secrets (typical)

- `API_KEYS`
- `API_KEY_TENANT_MAP`
- `OPENAI_API_KEY`
- `ATTESTATION_HMAC_SECRET`
- `EVIDENCE_SIGNING_SECRET`
- `SLACK_SIGNING_SECRET`
- `SLACK_BOT_TOKEN`
- `TEAMS_BRIDGE_SECRET`
- `LARK_VERIFICATION_TOKEN`
- `LARK_TENANT_ACCESS_TOKEN`

### Secret management principles

- Store all runtime secrets in cloud secret managers.
- Sync to Kubernetes with External Secrets or equivalent GitOps-safe workflows.
- Rotate `API_KEYS` and dependent upstream keys on a scheduled cadence.
- Never commit resolved secrets to `.env`, values files, or overlays.

---

## Example: managed data + secret-backed app config

```yaml
global:
  appSecretsName: tarka-app-secrets
  externalServices:
    postgres:
      enabled: true
      databaseUrl: postgresql+asyncpg://fraud:${DB_PASSWORD}@db.internal:5432/fraud
    redis:
      enabled: true
      redisUrl: rediss://cache.internal:6379/0
    neo4j:
      enabled: true
      uri: bolt+s://graph.internal:7687
      user: neo4j
      password: ${NEO4J_PASSWORD}
    nats:
      enabled: true
      url: nats://stream.internal:4222
    clickhouse:
      enabled: true
      host: analytics.internal
      port: 8443
      user: fraud_writer
      password: ${CLICKHOUSE_PASSWORD}
      database: fraud
```

---

## Operational checks for managed mode

- Connectivity check: every service can resolve and connect to managed dependencies.
- TLS check: Postgres/Redis/graph endpoints require encrypted transport.
- Permission check: each workload only reads secrets it needs.
- Rotation check: secret updates do not require manifest rewrites.
- Capacity check: queue lag, DB connection saturation, and cache eviction are monitored.
