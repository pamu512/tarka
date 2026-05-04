# batch-ingest

Offline historical backfill worker. Inserts rows into ClickHouse `fraud_features_offline` from CSV.

**Guarantees**

- Does **not** connect to NATS.
- Does **not** call `decision-api` or publish to `fraud.decisions.>`.
- Uses a line checkpoint file to resume after failures.

**Environment**

| Variable | Description |
|----------|-------------|
| `BATCH_CSV_PATH` | Path to CSV (required unless `--csv`). |
| `CLICKHOUSE_HOST` | Not used directly; pass `--clickhouse-url`. |
| Default URL | `http://localhost:8123` |

**CSV columns**

- `tenant_id` (required)
- `entity_id` (required)
- `observed_at` or `event_time` or `timestamp` (required)
- Additional columns are folded into `vector_json` as JSON.

**Run**

```bash
cargo run --release -- --csv ./data/history.csv --clickhouse-url http://clickhouse:8123 --clickhouse-database fraud
```
