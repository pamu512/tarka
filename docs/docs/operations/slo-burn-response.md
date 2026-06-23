# SLO burn response runbook

Use when **TarkaHighErrorRate***, **TarkaRiskServiceHighErrorRate***, or **TarkaDecisionApiCircuitOpen*** alerts fire from [slo-burn.yml](../../../infra/deploy/observability/prometheus-rules/slo-burn.yml).

## Severity mapping

| Alert label `severity` | Response | Target ack |
|------------------------|----------|------------|
| `warning` | Investigate within 30m; page if burn persists >1h | On-call Slack |
| `critical` (if configured) | Immediate mitigation | PagerDuty / phone |

## 5m fast burn (TarkaHighErrorRate5m, TarkaRiskServiceHighErrorRate5m)

1. Open Grafana **Tarka SLO burn (5m vs 1h)** dashboard (`uid: tarka-slo-burn`).
2. Identify `service` label on the firing alert.
3. `curl -sS "http://<host>:<port>/v1/slo"` for that service (see [service-slos-v1.md](../guides/service-slos-v1.md)).
4. Check `/metrics` for `http_requests_total` by `status` and `path`.
5. If **decision-api** circuit alerts co-fire, see [fallback-emergency-runbook.md](../guides/fallback-emergency-runbook.md).
6. Roll back recent deploy if error spike correlates with release (see [runbook-common-failures.md](./runbook-common-failures.md)).

## 1h slow burn (TarkaHighErrorRate1h, TarkaRiskServiceHighErrorRate1h)

1. Confirm whether 5m window has recovered; if both hot, treat as incident.
2. Review error budget consumption vs monthly target in `/v1/slo` JSON.
3. Schedule fix-forward or capacity change; document in incident channel.
4. For **calibration-service**, **counter-service**, **location-service**: verify upstream Redis/Postgres and dependency URLs in compose/Helm values.

## Circuit / fallback alerts (decision-api)

| Alert | First checks |
|-------|----------------|
| TarkaDecisionApiCircuitOpenCalibration | `GET /v1/slo` on calibration-service; logs for timeout |
| TarkaDecisionApiCircuitOpenCounter | counter-service health; `scripts/replay/` parity if counters stale |
| TarkaDecisionApiCircuitOpenLocation | location-service health; geo fallback tags in audit |
| TarkaDecisionApiCircuitOpenExternal | integration-ingress connector status |
| TarkaDecisionApiFallbackRateElevated | `fraud_fallback_total`, `fallback_reason` in evaluate audit payloads |

## Core platform services (extended coverage)

When burn alerts reference these `service` labels, use the linked runbook section in [runbook-common-failures.md](./runbook-common-failures.md):

| Service | Compose port (default) |
|---------|------------------------|
| decision-api | 8000 |
| case-api | 8002 |
| integration-ingress | 8003 |
| feature-service | 8004 |
| ml-scoring | 8005 |
| event-ingest | 8007 |
| graphql-gateway | 8080 |
| investigation-agent | 8010 |
| analytics-sink | 8012 |

## Escalation

1. On-call engineer (primary)
2. Platform / SRE lead if burn >2h or customer-facing SLA at risk
3. Post-incident: update [runbook-pack-index.md](./runbook-pack-index.md) if a gap was found

## Related

- [Runbook pack index](./runbook-pack-index.md)
- [Service SLOs (v1)](../guides/service-slos-v1.md)
- [Fallback & emergency](../guides/fallback-emergency-runbook.md)
