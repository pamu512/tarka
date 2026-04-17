# Service SLOs (v1) — reference

**Purpose:** Single place for **aspirational** availability and latency targets for core Tarka services. **Actual** SLO attainment comes from your metrics stack (Prometheus + Grafana, Datadog, etc.). Each service exposes **`GET /v1/slo`** with **targets** plus **current** in-process HTTP counters where observability middleware is enabled.

## Targets (defaults)

| Service | Port (compose) | Availability (monthly) | p95 latency (HTTP) | Notes |
|---------|----------------|-------------------------|--------------------|--------|
| decision-api | 8000 | 99.9% | 50 ms | Hot path evaluate |
| case-api | 8002 | 99.9% | 200 ms | Case CRUD + webhooks |
| feature-service | 8004 | 99.9% | 150 ms | Snapshot + velocity reads |
| ml-scoring | 8005 | 99.9% | 120 ms | Score endpoint |
| integration-ingress | 8010 | 99.9% | 500 ms | Enrich / connectors |
| event-ingest | 8007 | 99.9% | 200 ms | Accept + NATS publish |

**Queue lag** (NATS consumer pending messages, JetStream lag) should be monitored separately; not included in **`/v1/slo`** JSON today.

## Runtime surface

- **`GET /v1/slo`** — JSON: `availability_target_pct` or `availability_target`, `latency_target_ms_p95`, `error_budget_window_days`, `current` (service-specific + `http_requests_total_observed` from in-process middleware when available).

## Burn-rate alerts (operator pattern)

Use **two windows** on error rate or latency: **5m** (fast burn) and **1h** (slow burn) vs budget.

**Shipped:** Prometheus loads **[prometheus-rules/slo-burn.yml](../../deploy/observability/prometheus-rules/slo-burn.yml)** (recording rules `tarka:http_5xx_ratio_5m` / `tarka:http_5xx_ratio_1h` plus example alerts). Grafana folder **Tarka** includes **Tarka SLO burn (5m vs 1h)**.

Legacy standalone example: **[slo-burn-recording-rules.example.yml](../../deploy/observability/slo-burn-recording-rules.example.yml)**.

## Degradation (R2)

**decision-api** wraps list / graph / feature-service / ml-scoring / OPA outbound calls with **async circuit breakers** (env `CIRCUIT_*`). When open, evaluate **fail-opens** with fallbacks and adds signal tags: `lists:unavailable`, `graph:unavailable`, `enrichment:unavailable`, `ml:unavailable`, `opa:unavailable`. Prometheus: `tarka_circuit_open_total_*` counters on **decision-api** `/metrics`.

## Related

- [Deployment](deployment.md)
