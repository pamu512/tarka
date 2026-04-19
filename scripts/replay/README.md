# Counter replay worker

Offline replay rebuilds Redis-backed aggregates from JSONL exports using the same `AggregateStore` logic as the Decision API.

See [counter replay parity](../../docs/docs/guides/counter-replay-parity.md) and [ingest & replay onboarding](../../docs/docs/guides/ingest-replay-onboarding.md).

## Usage

```bash
# From repo root — validate file only
python scripts/replay/replay_aggregates.py --input audits.jsonl --dry-run

# Replay into a scratch Redis database (e.g. DB 15)
python scripts/replay/replay_aggregates.py --input audits.jsonl --redis-url redis://localhost:6379/15

# Process at most N rows
python scripts/replay/replay_aggregates.py --input audits.jsonl --redis-url redis://localhost:6379/15 --limit 1000
```

### Replay a specific date range

Filter rows by event timestamp (`ts`/`timestamp`/`created_at`) before writing:

```bash
python scripts/replay/replay_aggregates.py \
  --input audits.jsonl \
  --redis-url redis://localhost:6379/15 \
  --from 2026-04-01T00:00:00Z \
  --to 2026-04-07T23:59:59Z
```

Accepted time formats:
- Unix epoch seconds (`1712345678` or `1712345678.5`)
- ISO-8601 strings (`2026-04-01T12:30:00Z`)
- Naive ISO strings are interpreted as UTC.

Compare key counts or field sums against production using the same tenant/entity keys (`fraud:agg:...` — see `decision_api.aggregates`).

## Prod vs scratch diff

With `redis` installed (`pip install redis`):

```bash
python scripts/replay/diff_aggregate_redis.py \
  --left-url redis://localhost:6379/0 \
  --right-url redis://localhost:6379/15 \
  --pattern 'fraud:agg*'
```

Exit code **0** if all matched ZSETs are identical; **1** if any key is missing on one side or member/score pairs differ.

## One-shot parity report

`run_offline_parity.py` runs replay into scratch Redis, optionally diffs against a reference Redis, and writes a JSON report:

```bash
python scripts/replay/run_offline_parity.py \
  --input scripts/replay/fixtures/parity_smoke.jsonl \
  --scratch-url redis://localhost:6379/15 \
  --reference-url redis://localhost:6379/0 \
  --report /tmp/parity_report.json
```

## Export `decision_audit` to JSONL

```bash
export DATABASE_URL=postgresql+psycopg://user:pass@host:5432/tarka
python scripts/replay/export_audit_to_jsonl.py \
  --tenant-id acme --entity-id user-42 --out /tmp/audit.jsonl --limit 5000
```

Uses **`payload_snapshot.payload`** as aggregate **`fields`** (same as evaluate). Then replay with **`replay_aggregates.py`** as above.

## HTTP: replay from audit (Decision API)

With **`COUNTER_REPLAY_TOKEN`** set and header **`X-Tarka-Counter-Replay-Token`**:

`POST /v1/internal/counters/replay/from-audit` — JSON body `scratch_redis_url`, `tenant_id`, `entity_id`, optional `limit` (max 20_000).

## Fixture for CI

[`fixtures/parity_smoke.jsonl`](fixtures/parity_smoke.jsonl) — used by [`.github/workflows/counter-parity-smoke.yml`](../../.github/workflows/counter-parity-smoke.yml).

## Changing Redis key prefix (`AGG_KEY_VERSION`)

See **[redis-agg-key-version-migration.md](../../docs/docs/guides/redis-agg-key-version-migration.md)** for production migration strategies and rollback.
