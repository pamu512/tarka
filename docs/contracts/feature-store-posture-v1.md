# Feature-store posture v1

| Layer | What it is | Tip status |
|-------|------------|------------|
| L0 | Event fields | Always on |
| L1 | Redis velocity counters | Tip. Not a production online FS. |
| L2 | Point-in-time online serve (`GET /v1/features/{entity_type}/{entity_id}?as_of=`) | On only when `FEATURE_STORE_URL` is set. Empty = off. Evaluate fail-soft on miss/timeout (not 500). Optional stream + jsonl backfill writers; empty URL = no L2 writes. Writer lag must not fail evaluate. L2 does not decide ALLOW/DENY/Promote/demote. |
| L3 | Warehouse / export | Buyer-owned ([warehouse-sink-v1](warehouse-sink-v1.md)). PIT golden + `holdout_split` are offline/sidecar; model never ALLOW/DENY. |

`feast_class_claim_allowed` stays **false**. Optional L2 PIT serve via `FEATURE_STORE_URL` is not Feast. Redis dual-diff is L1 proof, not a production online FS.

Receipt field: `feature_source=l2|l1|raw` matches the path actually used (never fake `l2` on miss/timeout).

Product field-registry overlays persist in Postgres. Demo PUTs may 403 / stay fixture-only.

## L1 ownership split (2026-09)

Two distinct L1 Redis populations; neither is a shared "counter service" (that was deleted — write-only hop):

| Keys | Writer | Reader | Notes |
|------|--------|--------|-------|
| aggregate counters (`fraud_aggregates.AggregateStore`) | decision-api, local ownership | decision-api evaluate | Formerly counter-service remote fetch; flipped local. Circuit/metrics/env (`COUNTER_SERVICE_URL`) removed. |
| `anumana:velocity:t:{tenant}:device|card|ip:{win}:{token}:{bucket}` (+`:amt`) | orchestrator `velocity_update` handler, Redis MULTI/EXEC (sole channel) | decision-api `anumana_signals` → evaluate features | ClickHouse mirror removed (write-only). Keys are TTL-bucketed counters, not a production online FS. |

Removed write-only surfaces (no readers anywhere): `anumana:consortium:threat:*` + CH `orchestrator_consortium_threat_counters` (worker deleted; labels publishes continue), NATS `tarka.hypothesis.deployed` / `tarka.hypothesis.promoted` (Redis hypothesis deploy is the delivery channel; `shadow_hypothesis.py` reads it).

See [feature-data-flows](../docs/guides/feature-data-flows.md).
