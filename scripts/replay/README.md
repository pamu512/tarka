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
