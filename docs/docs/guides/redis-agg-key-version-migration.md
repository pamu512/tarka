# Redis aggregate key version (`AGG_KEY_VERSION`) — operator playbook

Velocity counters use Redis sorted sets under **`fraud:agg:`** (and **`fraud:aggval:`**). When **`AGG_KEY_VERSION`** is set to a non-empty alphanumeric string (also allowing `._:-`), keys become:

`fraud:agg:{version}:{tenant_id}:{entity_id}:{metric}`

An **empty** or unset variable keeps **legacy** keys: `fraud:agg:{tenant_id}:{entity_id}:{metric}`.

This playbook is for **changing** the version in production without silently splitting traffic across two key namespaces.

## When to bump the version

- You changed **aggregate semantics** (window definitions, which fields feed distinct counts, etc.) and old ZSET members are incompatible with new readers.
- You need a **clean cut** for compliance or forensic reasons (document the reason in the change ticket).

## Preconditions

- **Same version everywhere writers run:** decision-api, event-ingest workers (if they record aggregates), offline **`replay_aggregates.py`**, and **`POST /v1/internal/counters/replay`** processes must all use the **same** `AGG_KEY_VERSION` value when targeting the **same** Redis.
- **feature-service** only **reads**; it must match the prefix decision-api uses (same env on shared Redis).
- **`GET /v1/internal/counters/manifest`** echoes **`redis_key_version`** when the env var is valid — use it after deploy to confirm.

## Migration strategies

### A) Big-bang switch (small Redis / acceptable cold start)

1. **Maintenance window** (optional): stop or drain writers that increment counters.
2. Set **`AGG_KEY_VERSION=new_v2`** on all services and jobs; deploy.
3. **Legacy keys are orphaned** until TTL/expiry (ZSETs use long TTLs); optionally **`SCAN` + `DEL`** legacy `fraud:agg:*` keys in a controlled script if storage or confusion is a problem (coordinate with SRE — **destructive**).
4. Traffic resumes; counters **rebuild from new events** only.

### B) Blue/green Redis (no mixed keys in one DB)

1. Provision a **new** Redis endpoint (or empty DB index, e.g. `/1` vs `/0`).
2. Point **new** deployment at **`AGG_KEY_VERSION=new_v2`** and the **new** Redis.
3. Cut over load balancers; **old** Redis retains legacy keys for rollback.
4. Decommission old Redis after the retention window.

### C) Replay backfill (keep history)

1. Export **`decision_audit`** (or event archive) to JSONL — see **`scripts/replay/export_audit_to_jsonl.py`**.
2. Run **`replay_aggregates.py`** with **`AGG_KEY_VERSION=new_v2`** against the **target** Redis (scratch DB first, validate).
3. Use **`diff_aggregate_redis.py`** between a **sample** entity on old vs replayed new keys if you dual-write temporarily (advanced).

## Rollback

- Revert **`AGG_KEY_VERSION`** to the previous value (or unset for legacy) and redeploy.
- If you already deleted legacy keys, rollback only restores **new** events after the revert — plan TTLs and backups accordingly.

## Verification checklist

- [ ] **`GET /v1/internal/counters/manifest`** shows expected **`redis_key_version`**.
- [ ] Spot-check **`ZCARD`** on a known **`fraud:agg:...:events`** key for a test tenant after traffic.
- [ ] **`POST /v1/velocity/query`** (feature-service) matches decision-api counts for the same tenant/entity when sharing Redis.
- [ ] Weekly **`counter-parity-smoke`** workflow green (or manual runbook in **`counter-replay-parity.md`**).

## Related

- **[counter-replay-parity.md](./counter-replay-parity.md)** — Epic C parity, replay API, runbook.
- **`services/shared/fraud_aggregates.py`** — key construction.
- **`scripts/replay/README.md`** — CLI replay and diff.
