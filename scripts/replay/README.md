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
