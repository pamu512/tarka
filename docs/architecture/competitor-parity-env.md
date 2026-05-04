# Competitor parity — environment variables

**Full guide (endpoints, flows, code paths):** [docs/docs/guides/competitor-parity.md](../docs/guides/competitor-parity.md)

| Variable | Service | Purpose |
|----------|---------|---------|
| `INGEST_REDIS_URL` | event-ingest | Cross-replica mapping cache for `/v1/ingest/dynamic`. |
| `INGEST_PII_TOKENIZE` | event-ingest | Tokenize before mapping samples + standard ingest. |
| `BATCH_CSV_PATH` | batch-ingest | CSV path for offline ClickHouse backfill. |
| `CASE_QUEUE_ROUTING_RULES_JSON` | case-api | JSON array routing rules for `assigned_team`. |
| `FINCEN_BSA_SFTP_HOST` | case-api | Enables SAR ACK poll scheduling (stub until worker ships). |
| `ML_MODEL_WEBHOOK_SECRET` | ml-scoring | Optional header `x-ml-webhook-secret` for `POST /v1/models/reload`. |
| `DASHBOARD_KPI_CACHE_TTL_SECONDS` | decision-api | Redis TTL for `/v1/analytics/dashboards/kpis`. |

See also: [graph-service decision stream indexer](../../services/graph-service/docs/DECISION_STREAM_INDEXER.md).
