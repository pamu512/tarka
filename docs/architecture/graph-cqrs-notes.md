# Apache AGE graph + CQRS evaluation

## Operational vs analytical split

- **Operational (low latency):** 1–2 hop traversals on Apache AGE for entity/device edges used during
  `POST /v1/decisions/evaluate` (see `graph-service` entity-risk endpoints).
- **Analytical (high depth):** ring detection / community metrics materialized into ClickHouse via
  `analytics-sink` and batch jobs. Analysts query ClickHouse for multi-hop patterns; the hot path
  never performs unbounded graph walks.

## Benchmark harness

Run `python3 scripts/benchmarks/age_graph_bench.py --help` to compare simple Cypher templates against
local Postgres+AGE. Use results to decide when to promote a query from synchronous evaluate to a
materialized view.
