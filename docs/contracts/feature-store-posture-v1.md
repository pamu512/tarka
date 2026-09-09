# Feature-store posture v1

| Layer | What it is | Tip status |
|-------|------------|------------|
| L0 | Event fields | Always on |
| L1 | Redis velocity counters | Tip. Not a production online FS. |
| L2 | Point-in-time online serve (`GET /v1/features/{entity_type}/{entity_id}?as_of=`) | On only when `FEATURE_STORE_URL` is set. Empty = off. Evaluate fail-soft on miss/timeout (not 500). Optional stream + jsonl backfill writers; empty URL = no L2 writes. Writer lag must not fail evaluate. L2 does not decide ALLOW/DENY/Promote/demote. |
| L3 | Warehouse / export | Buyer-owned ([warehouse-sink-v1](warehouse-sink-v1.md)) |

`feast_class_claim_allowed` stays **false**. Optional L2 PIT serve via `FEATURE_STORE_URL` is not Feast. Redis dual-diff is L1 proof, not a production online FS.

Receipt field: `feature_source=l2|l1|raw` matches the path actually used (never fake `l2` on miss/timeout).

Product field-registry overlays persist in Postgres. Demo PUTs may 403 / stay fixture-only.

See [feature-data-flows](../docs/guides/feature-data-flows.md).
