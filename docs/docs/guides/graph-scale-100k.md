# Graph load profile at 100k entities (G2 re-bench)

Measured 2026-09-24, master + perf commits (7431dd9d, db28556a, a08fb18d),
tarka-full desk (Apple Silicon, Docker Desktop, postgres+AGE single node).

Volume: 50,000 Person + 20,000 Device + 30,000 Payment = 100,000 vertices,
100,200 edges (per-person USED_DEVICE + MADE_PAYMENT, 200 hub edges), tenant
`load100k`, WORKERS=8.

## Writes

| Phase | Rate |
|---|---|
| persons | 762/sec |
| devices | 836/sec |
| payments | 772/sec |
| links (100,200) | completed fully — no 502s after the DDL-race retry (58d368c5) |

## Reads (p50 over probe runs, post directed-walk fix)

| Query | Before | After (p50 / p95, n=25) |
|---|---|---|
| subgraph depth-1 (hub) | 16+ min / timeout | 283ms / 417ms |
| subgraph depth-2 (person) | 16+ min / timeout | 273ms / 325ms |
| subgraph 2-hop as-of (bitemporal) | n/a (never completed) | 268ms / 325ms |
| entity search (prefix) | 5ms (small graph) | 5ms / 7ms |
| entity-risk (analytics) | 29+ min / timeout | 2.86s / 3.04s |

The before-numbers are not typos: the previous undirected OR-join walk
(`MATCH (n)-[r]-(m)` with property filters on both endpoints) had planner
cost ~8.9e8 at this volume and nested-looped the edge space. The two-phase
directed walk (anchor graphid resolved via the (tenant_id, external_id)
index, then directed `id(root) = <const>` edge queries on
ix_<label>_start/_end) made the same reads sub-second-to-seconds.

This replaces the stale X-30 stat (p50 6.7s @ 1.1k entities) as the
reference scale point. Reproduce:

```bash
GRAPH_API=http://127.0.0.1:8001 TENANT=load100k PERSONS=50000 DEVICES=20000 \
  PAYMENTS=30000 HUB_EDGES=200 WORKERS=8 python3 scripts/benchmarks/graph_load_profile.py
```

Bench = product finder: this re-bench surfaced two real bugs (edge-label DDL
race on concurrent first-links; undirected walk plan collapse), both fixed
with behavioral tests (`test_link_ddl_race.py`, `test_subgraph_plan_shape.py`).
