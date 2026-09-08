# Production observability (thin)

Prometheus scrape plus two example alerts for **evaluate 5xx** and **evaluate latency**. This is not a full Observability SKU: no tracing product, no dashboard pack, no paging topology.

Service mesh (Istio or otherwise) stays **optional**. NetworkPolicy and ServiceMonitor do not require a mesh.

## What prod emits

`presets/prod-on-k8s.yaml` sets `global.environment: prod` and turns NetworkPolicy + ServiceMonitor on:

```yaml
global:
  networkPolicy:
    enabled: true
  serviceMonitor:
    enabled: true
```

The same objects also emit when `TARKA_DEPLOYMENT_PROFILE=production` even if `global.environment` is still `dev` (unset flags follow that production profile).

| Object | core-api path |
|--------|----------------|
| `NetworkPolicy` `*-default-deny` | Deny all ingress/egress, then allow listed hops |
| `NetworkPolicy` `*-allow-ingress-core-api` | TCP `8000` onto `app: <release>-tarka-core-api` (evaluate + `/metrics`) |
| `ServiceMonitor` `*-core-api` | Prometheus Operator scrape `port: http` `path: /metrics` every 30s |

`lite-on-k8s` and default `values.yaml` (`global.environment: dev`) emit **neither**. Local clusters stay open.

Proof:

```bash
python3 infra/scripts/deploy/generate_cloud_values.py \
  --preset prod-on-k8s \
  --image-registry registry.example.com/tarka \
  --db-url 'postgresql+asyncpg://fraud:pw@db.internal:5432/fraud' \
  --redis-url 'rediss://redis.internal:6379/0' \
  --allow-empty-digest \
  --output /tmp/prod-on-k8s.values.yaml
helm template tarka infra/deploy/helm/fraud-stack -f /tmp/prod-on-k8s.values.yaml \
  | grep -E 'kind: (NetworkPolicy|ServiceMonitor)|name: .*core-api|port: 8000|path: /metrics'
```

`--allow-empty-digest` is a non-grade `helm template` of placeholders, not an immutable pin. The cluster must already run Prometheus Operator. The chart does not install Prometheus.

## Opt-out

Leave the production profile / `prod-on-k8s` fail-closes in place and disable only these objects:

```bash
--set global.networkPolicy.enabled=false
--set global.serviceMonitor.enabled=false
```

Do not flip `global.environment` to `dev` just to skip policies.

## Scrape

Shared middleware already exposes `/metrics` (`http_requests_total`, `http_request_duration_seconds_*`, `http_server_errors_total`). ServiceMonitors select the existing `app` label and Service `http` port. Ingress NetworkPolicy on core-api allows TCP 8000 from any namespace, so a Prometheus in `monitoring` can scrape without Istio.

Enabled HTTP APIs that already publish `/metrics`:

| Service | Compose port | Helm Service port |
|---------|--------------|-------------------|
| core-api (evaluate) | 8000 | `coreApi.servicePort` |
| signal-api | 8004 | `signalApi.servicePort` |
| investigation-agent | 8006 | `investigationAgent.servicePort` |

## Example alerts (evaluate)

Shipped 5xx burn rules: [slo-burn.yml](../../../infra/deploy/observability/prometheus-rules/slo-burn.yml). Evaluate is the core-api / decision-api `POST /v1/decisions/evaluate` series.

```yaml
groups:
  - name: tarka_evaluate_examples
    rules:
      - alert: TarkaEvaluateHigh5xx
        expr: |
          sum(rate(http_requests_total{service=~"core-api|decision-api",path="/v1/decisions/evaluate",status=~"5.."}[5m]))
          /
          clamp_min(sum(rate(http_requests_total{service=~"core-api|decision-api",path="/v1/decisions/evaluate"}[5m])), 1e-9)
          > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Evaluate 5xx ratio > 5% (5m)"

      - alert: TarkaEvaluateHighLatency
        expr: |
          sum(rate(http_request_duration_seconds_sum{service=~"core-api|decision-api",path="/v1/decisions/evaluate"}[5m]))
          /
          clamp_min(sum(rate(http_request_duration_seconds_count{service=~"core-api|decision-api",path="/v1/decisions/evaluate"}[5m])), 1e-9)
          > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Evaluate mean latency > 50ms (5m)"
```

Tune thresholds against [Service SLOs](service-slos-v1.md). These examples are operator-owned; the chart does not ship Alertmanager or Grafana as a product.

## Out of scope

- Istio / service mesh required
- Full alerting product (routing, on-call, SLO burn as a SKU)
- Inventing `values.networkPolicy.egressCIDRs` — tighten managed PG/Redis with your own `ipBlock` if you need VPC CIDRs
