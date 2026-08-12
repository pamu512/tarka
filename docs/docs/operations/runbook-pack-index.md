# Runbook pack index

Unified index for on-call and release operators. Linked from Prometheus `runbook_url` annotations and Grafana dashboards.

## Emergency and degradation

| Runbook | When to use |
|---------|-------------|
| [SLO burn response](./slo-burn-response.md) | Prometheus SLO / circuit / fallback alerts |
| [Fallback & emergency](../guides/fallback-emergency-runbook.md) | Decision-api degrade mode, kill switches, fail-open paths |
| [Common failures](./runbook-common-failures.md) | Service won't start, DB/Redis/NATS, auth 401/403 |
| [On-call playbook](./oncall-playbook.md) | Rotation, escalation, comms templates |

## Data integrity and counters

| Runbook | When to use |
|---------|-------------|
| [Counter replay parity](../guides/counter-replay-parity.md) | Epic C parity failures, AGG_KEY_VERSION cutover |
| [Chaos template](./runbook-common-failures.md) | Planned chaos / game-day exercises |

## Release and security

| Runbook | When to use |
|---------|-------------|

## Observability entry points

- Grafana: **Tarka SLO burn (5m vs 1h)** (`uid: tarka-slo-burn`)
- Prometheus rules: [slo-burn.yml](../../../infra/deploy/observability/prometheus-rules/slo-burn.yml)
- SLO targets: [service-slos-v1.md](../guides/service-slos-v1.md)

## Maintenance

When adding a new alert rule, attach `runbook_url` pointing to a section in this index or a child runbook.
