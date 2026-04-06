# Consortium signal adapter

Small **HTTP client + CLI** for Tarka Decision API consortium endpoints (`/v1/consortium/*`): share signals, check aggregates, post feedback, set tenant trust, and **batch ingest** from JSON Lines.

This is **not** a third-party consortium SDK; it talks to **your** decision-api instance. Server-side **`CONSORTIUM_SECRET`**, Redis, and **`CONSORTIUM_ENABLED`** must match your deployment ([`joinsonar-query-feedback-vs-consortium-api.md`](../../docs/docs/guides/joinsonar-query-feedback-vs-consortium-api.md)).

## Setup

From repo root (requires `httpx`; same as [`scripts/requirements.txt`](../requirements.txt)):

```bash
pip install httpx
```

## Environment

| Variable | Purpose |
|----------|---------|
| `TARKA_DECISION_API_URL` | Base URL (default `http://127.0.0.1:8000`) |
| `TARKA_API_KEY` | Optional `X-API-Key` when decision-api enforces `API_KEYS` |

## CLI

```bash
# Share a signal
python scripts/consortium_adapter/cli.py share \
  --tenant-id acme --entity-id user-1 --signal-type account_takeover --severity 2.0

# Check aggregate (same tenant_id + entity_id hashing as evaluate)
python scripts/consortium_adapter/cli.py check --tenant-id acme --entity-id user-1

# Feedback after review
python scripts/consortium_adapter/cli.py feedback \
  --tenant-id acme --entity-id user-1 --outcome confirmed_fraud

# Tenant trust weight (0.1–2.0)
python scripts/consortium_adapter/cli.py trust --tenant-id acme --trust-score 1.2

# Batch file (see examples/sample_ingest.jsonl)
python scripts/consortium_adapter/cli.py ingest scripts/consortium_adapter/examples/sample_ingest.jsonl
python scripts/consortium_adapter/cli.py ingest scripts/consortium_adapter/examples/sample_ingest.jsonl --dry-run
```

Override URL/key per run: `--url https://decision.example.com --api-key secret`.

## Python API

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts/consortium_adapter").resolve()))
from client import ConsortiumAdapter, ingest_json_lines

adapter = ConsortiumAdapter("http://127.0.0.1:8000", api_key="optional")
adapter.share_signal("tenant", "entity", "signal_type", severity=1.5)
adapter.close()
```

Or install path so `import consortium_adapter` works with `sys.path` including `scripts`.

## JSON Lines ingest format

One JSON object per line. Lines starting with `#` are comments. Fields:

| `op` | Required fields | Optional |
|------|-----------------|----------|
| `share` | `tenant_id`, `entity_id`, `signal_type` | `severity`, `ttl_days`, `consortium_id` |
| `check` | `tenant_id`, `entity_id` | `consortium_id` |
| `feedback` | `tenant_id`, `entity_id`, `outcome` (`false_positive` \| `confirmed_fraud`) | `ttl_days`, `consortium_id` |
| `trust` | `tenant_id`, `trust_score` | `consortium_id` |

## Tests

```bash
python -m pytest scripts/consortium_adapter/test_adapter.py --tb=short
```
