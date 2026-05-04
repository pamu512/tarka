# Runbook: Common Failures

## Redis Memory Pressure
- Symptoms: `OOM command not allowed`, rising latency, dropped writes.
- Immediate actions:
  - Check memory: `redis-cli INFO memory`.
  - Enable eviction policy for cache-style keys.
  - Increase memory limit or reduce retention windows for counter/event streams.
- Follow-up:
  - Lower stream maxlen and aggregate retention.
  - Add alert on `used_memory_ratio > 0.85`.

## Postgres Lock Contention
- Symptoms: long transactions, blocked writes, deadlock errors.
- Immediate actions:
  - Find blockers using `pg_stat_activity` and `pg_locks`.
  - Cancel oldest blocking transaction.
  - Reduce concurrent workers in data ingestion until queue stabilizes.
- Follow-up:
  - Add indexes for frequent filter/order columns.
  - Keep transactions short; avoid large multi-table writes in one txn.

## Circuit Breaker Storms
- Symptoms: many `circuit open` errors and fallback reason spikes.
- Immediate actions:
  - Verify upstream health before raising thresholds.
  - Temporarily increase `recovery_seconds` to avoid hot-loop retries.
  - Route traffic to degraded mode with explicit analyst banner.
- Follow-up:
  - Recalibrate per-dependency thresholds from incident metrics.
  - Add SLO alerts on open-circuit counters and fallback ratio.

