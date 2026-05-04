# On-Call Playbook (3 AM Scenarios)

## Redis OOM
- Confirm with `redis-cli INFO memory`.
- Reduce ingest pressure (lower producer rate, pause non-critical consumers).
- Flush non-critical keys only; do not delete core counters without approval.
- Escalate to platform owner if sustained >15 minutes.

## Postgres Locks / Deadlocks
- Inspect blockers in `pg_stat_activity`.
- Cancel blocking session with highest age and lowest business impact.
- Enable degraded mode for heavy write paths until lock queue drains.
- Escalate to DB owner if lock waits persist >10 minutes.

## Circuit Breaker Storm
- Identify failing dependency from fallback tags and circuit counters.
- Confirm dependency health before reopening traffic.
- Temporarily widen backoff and lower concurrent workers.
- Escalate to service owner if external dependency remains unstable.

## Escalation Path
- L1: On-call engineer (triage, mitigate, communicate).
- L2: Service owner (dependency-specific recovery).
- L3: Platform lead (cross-service rollback/degraded-mode decision).

