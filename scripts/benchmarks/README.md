# Benchmarks and load smoke tests

## Decision API latency (`latency_evaluate.py`)

Requires a running Decision API (e.g. lite compose). Uses **stdlib only** (no pip install).

```bash
# From repo root, with stack up on localhost:8000
python scripts/benchmarks/latency_evaluate.py --url http://127.0.0.1:8000 --requests 500 --concurrency 25 --warmup 10
```

Optional custom JSON body:

```bash
python scripts/benchmarks/latency_evaluate.py --payload-file my_event.json --requests 200
```

### Publishing results (honest checklist)

Record:

- **Host:** CPU model, RAM, disk, cloud SKU or bare metal.
- **Stack:** `docker compose` file and **profiles**; image tags or commit SHA.
- **Network:** same machine vs LAN vs remote.
- **Warm-up:** count and whether the DB was cold.
- **Payload:** size and feature shape (fraud vs login vs custom).

TPS ≈ `requests / wall_clock_seconds` (use `/usr/bin/time` or PowerShell `Measure-Command` around the script).

## Simulation metrics (precision / recall / F1)

For **labeled synthetic** scenarios, use Decision API **`POST /v1/simulation/run`** and **`/v1/simulation/ab-test`** — see [shadow-and-ab-testing.md](../../docs/docs/guides/shadow-and-ab-testing.md). These are **not** substitutes for production holdouts unless you align distributions.

## Throughput tools

- **`load-hey-evaluate.sh`** — optional **[hey](https://github.com/rakyll/hey)** wrapper for `POST /v1/decisions/evaluate` (install `hey` via Go toolchain). Falls back to a single `curl` if `hey` is missing.

For heavier HTTP loads, add **k6** in CI or a separate workflow; keep **`latency_evaluate.py`** **dependency-free** for quick sanity checks.

## ML batch scoring (`ml_batch_score.py`)

Rows in CSV with **`tenant_id`**, **`entity_id`**, and feature columns are posted to **ml-scoring** **`POST /v1/score`** (v1.2 stretch). Requires **`httpx`** (`pip install -r scripts/requirements.txt`).

```bash
python scripts/ml_batch_score.py --url http://127.0.0.1:8005 --input features.csv --output scored.csv
```

Optional column **`features`**: JSON object merged over per-column feature fields. Reserved column names: `tenant_id`, `entity_id`, `event_type`, `features`, plus output columns `ml_score`, `ml_model`, `ml_summary`, `error`.

## Drift score smoke (`drift_score_smoke.py`)

Compares **mean heuristic scores** on two **seeded JSON** feature batches (`fixtures/drift_baseline.json` vs `fixtures/drift_shifted.json`). Fails if separation is too small (dead signal) or absurdly large. **No server** required with `--local` (imports `ml-scoring` from the repo).

```bash
# From repo root
python scripts/benchmarks/drift_score_smoke.py --local
```

Optional HTTP mode against running ml-scoring:

```bash
python scripts/benchmarks/drift_score_smoke.py --url http://127.0.0.1:8005
```

## CI smoke (GitHub Actions)

Workflow **[`.github/workflows/benchmark-smoke.yml`](../../.github/workflows/benchmark-smoke.yml)** runs weekly (and on `workflow_dispatch`):

- Redis + Decision API + `latency_evaluate.py` (lite stack).
- **`drift_score_smoke.py --local`** (heuristic drift separation gate).

These jobs sanity-check scripts and scoring behavior; they are not publishable load or calibration proofs.
