# Label join contract v1

Immutable join keys on evaluate receipt snapshots and late-label binds. W2 implements warehouse export and extra `label_kind`s against this schema — do not invent a parallel key set.

## Required on every evaluate receipt snapshot

| Field | Notes |
|-------|-------|
| `evaluation_token` | Primary join key |
| `trace_id` | Fallback with `tenant_id` |
| `tenant_id` | Required |
| `entity_id` | Required |

## Optional (never invent)

Present only when the event carried them: `order_id`, `promo_id`, `courier_id`, `merchant_id`, `payment_instrument_id`, `device_id`.

## `label_kind`

| Kind | Status |
|------|--------|
| `fp` | Tip-live (late-label webhook) |
| `fraud` | Tip-live |
| `other` | Tip-live |
| `promo_abuse` | Tip-live (W2.2) |
| `collusion` | Tip-live (W2.2) |
| `chargeback` | Tip-live as `label_kind`; chargeback **fields** (`dispute_outcome`, `chargeback_class`) still bind when `dispute.outcome` is set |

Chargeback is not the only label.

## Bind rules (`POST /v1/webhooks/late-label`, alias `/v1/webhooks/disposition`)

Runtime parameters (do not drift): `tenant_id`, `outcome`, `trace_id`, `evaluation_token`, `decision_token`, `label_kind`, `source`, `prior_override_id`, `entity_id`, `later_trace_id`, `fp_cost`.

1. Prefer `evaluation_token`.
2. Else `decision_token` (tip alias for the same receipt).
3. Else `trace_id` + `tenant_id`.
4. Fail closed if neither token nor `trace_id`+`tenant` resolves.

Late labels may arrive 30–120 days later. Never reconstruct features — bind to the frozen snapshot only. No snapshot → label may still be recorded; `trainable: false`.

## Warehouse export shape (docs; host is buyer)

- One row per receipt snapshot.
- One row per label bind.
- Join key = `evaluation_token` (primary).

Scheduled consume (buyer cron / lake upsert) is documented in [warehouse-sink-v1](warehouse-sink-v1.md). Tarka does not host the buyer warehouse.

## Out of scope

- Changing bind implementation (W2)
- Hosting a warehouse
- Treating chargeback as the only label
