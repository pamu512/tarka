# Observability add-on (Prometheus + Grafana)

Tarka services expose Prometheus text metrics at **`/metrics`** via `services/shared/observability.py`.

## Run with the main stack

From **`deploy/`**:

```bash
docker compose -f docker-compose.yml -f observability/docker-compose.addon.yml \
  --profile core --profile observe up -d
```

Add **`--profile graph --profile ml`** (etc.) if you want those containers up so Prometheus scrapes them successfully.

- **Prometheus:** http://localhost:9090  
- **Grafana:** http://localhost:3001 (default login `admin` / `admin` — change in production)

Provisioned dashboard: **Tarka / Tarka HTTP overview**.

## NATS / ClickHouse

NATS does not expose Prometheus metrics in the default JetStream image; use NATS monitoring ports and external exporters if you need time-series. ClickHouse has its own metrics endpoints — add a separate scrape job if you run analytics in production.

## Security

Do not expose **9090/3001** on public interfaces without authentication and network policy.
