# Observability add-on (Prometheus + Grafana)

Tarka services expose Prometheus text metrics at **`/metrics`** via `services/shared/observability.py`.

## Run with the main stack

From **`deploy/`**:

```bash
docker compose -f docker-compose.yml -f observability/docker-compose.addon.yml \
  --profile core --profile agent --profile observe up -d
```

Add **`--profile graph --profile ml`** (etc.) if you want those containers up so Prometheus scrapes them successfully. **`--profile agent`** runs **investigation-agent** so the copilot dashboard has data.

- **Prometheus:** http://localhost:9090  
- **Grafana:** http://localhost:3001 (default login `admin` / `admin` — change in production)

Provisioned dashboards (folder **Tarka**):

- **Tarka HTTP overview** — HTTP request rate and 5xx counters across services.
- **Tarka SLO burn (5m vs 1h)** — `tarka:http_5xx_ratio_*` recording rules and decision-api circuit-open rates (requires **`prometheus-rules`** volume; see `prometheus.yml` `rule_files`).
- **Investigation agent — copilot** — persona chat rates (`investigation` vs `orchestrator`), tool invocation rate, tool-error rate, orchestrator share, and tool-error ratio (all from `investigation-agent` `/metrics`).

Ensure the **`agent`** profile is enabled so `investigation-agent` is running and scraped; otherwise panels show no data.

**Deeper copilot KPIs** (`persona`, `tool_repeat_count`, `distinct_tool_names`) live in structured **logs** (`event` = `investigation_tool_quality`), not Prometheus — pipe container logs to Loki/ELK if you need those in Grafana.

## NATS / ClickHouse

NATS does not expose Prometheus metrics in the default JetStream image; use NATS monitoring ports and external exporters if you need time-series. ClickHouse has its own metrics endpoints — add a separate scrape job if you run analytics in production.

## Security

Do not expose **9090/3001** on public interfaces without authentication and network policy.
