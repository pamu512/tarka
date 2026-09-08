# Feature-store posture v1

| Layer | What it is | Tip status |
|-------|------------|------------|
| L0 | Event fields | Always on |
| L1 | Redis velocity counters | Tip. Not a production online FS. |
| L2 | Point-in-time online serve | On only when `FEATURE_STORE_URL` is set. Empty = off. |
| L3 | Warehouse / export | Buyer-owned ([warehouse-sink-v1](warehouse-sink-v1.md)) |

`feast_class_claim_allowed` stays **false** until a real L2 product exists. Redis dual-diff is L1 proof, not Feast.

Receipt field: `feature_source=l2|l1|raw`.

Product field-registry overlays persist in Postgres. Demo PUTs may 403 / stay fixture-only.

See [feature-data-flows](../docs/guides/feature-data-flows.md).
