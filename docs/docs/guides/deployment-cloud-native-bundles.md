# Cloud-native deployment bundles

This guide defines opinionated deployment bundles for cloud environments so teams can choose by business need instead of wiring every service manually.

These bundles map directly to existing module and profile behavior in `deploy/docker-compose.yml`, but are designed for Kubernetes and managed cloud runtimes.

---

## Bundle catalog


| Bundle          | Includes                                                                                | Optional                                                                     | Managed dependencies                           | Target scale envelope                            |
| --------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------ |
| `core`          | `decision-api`                                                                          | `feature-service`, `ml-scoring`, `opa`                                       | Postgres, Redis                                | Low-latency scoring and policy checks            |
| `investigation` | `case-api`, `investigation-agent`, `graphql-gateway`, `frontend`, `integration-ingress` | `graph-service`, `collaboration-chat-bridge`                                 | Postgres, Redis, optional graph store          | Analyst workflows and evidence reviews           |
| `streaming`     | `event-ingest`                                                                          | `decision-api` passthrough keying                                            | NATS, Redis, optional Postgres for metadata    | Async ingest and backpressure-tolerant pipelines |
| `analytics`     | `analytics-sink`                                                                        | dashboard/API surfaces consuming ClickHouse                                  | ClickHouse, NATS                               | Historical analytics and trend views             |
| `full`          | all above bundles                                                                       | risk services (`calibration-service`, `counter-service`, `location-service`) | Postgres, Redis, graph store, NATS, ClickHouse | Platform-wide multi-team fraud operations        |


---

## Bundle dependency contract

Each bundle is operated with the same contract:

1. **Application container layer**
  Tarka services run as independently deployable containers.
2. **Managed data layer**
  State is externalized to managed services where possible.
3. **Secrets and identity layer**
  Secrets come from cloud secret managers, not committed files.
4. **Ingress and policy layer**
  External access is mediated by cloud-native ingress and policy controls.

---

## Bundle-to-profile mapping


| Bundle          | Compose profiles (reference)                                           | Helm toggles (reference)                                                                                                                                                    |
| --------------- | ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `core`          | `core` (+ optional `ml`, `opa`)                                        | `decisionApi.enabled`, `featureService.enabled`, `mlScoring.enabled`                                                                                                        |
| `investigation` | `cases`, `agent`, `gateway`, `integration`, optional `graph`, `collab` | `caseApi.enabled`, `investigationAgent.enabled`, `graphqlGateway.enabled`, `integrationIngress.enabled`, optional `graphService.enabled`, `collaborationChatBridge.enabled` |
| `streaming`     | `streaming`                                                            | `eventIngest.enabled`, `nats.enabled` (or external NATS)                                                                                                                    |
| `analytics`     | `analytics`                                                            | `analyticsSink.enabled`, `clickhouse.enabled` (or external ClickHouse)                                                                                                      |
| `full`          | `full`                                                                 | all component toggles enabled                                                                                                                                               |


---

## Recommended bundle selection

- Choose `core` when you need a fast production pilot with minimum moving parts.
- Add `investigation` when analyst workflows and case triage are required.
- Add `streaming` for high-volume asynchronous event pipelines.
- Add `analytics` for long-term trend analysis and warehouse-style reporting.
- Use `full` only when you need complete platform parity in one environment.

---

## SLO planning hints

Use these as initial planning baselines, then validate with load tests.

- `core`: prioritize `decision-api` p95/p99 latency and Redis saturation.
- `investigation`: prioritize API availability and human workflow responsiveness.
- `streaming`: prioritize queue lag, consumer throughput, and deduplication hit rate.
- `analytics`: prioritize ingest-to-query freshness and query tail latency.
- `full`: monitor both interactive and pipeline SLOs to avoid noisy-neighbor coupling.

---

## Next steps

- For AWS service mapping, use `[deployment-aws.md](./deployment-aws.md)`.
- For GCP service mapping, use `[deployment-gcp.md](./deployment-gcp.md)`.
- For Kubernetes value presets and generated overlays, use `[deployment-presets.md](./deployment-presets.md)`.

