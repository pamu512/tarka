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

## CI smoke (GitHub Actions)

Workflow **[`.github/workflows/benchmark-smoke.yml`](../../.github/workflows/benchmark-smoke.yml)** runs weekly (and on `workflow_dispatch`): Redis service + Decision API (SQLite) + `latency_evaluate.py` with a small request count. It only proves the script and stack still work together, not publishable TPS.
