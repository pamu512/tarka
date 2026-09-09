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

## Horizon policy (`tarka.label_horizon/v1`)

Per-`label_kind` window used by join-rate glass (and later consume). **Tenant policy EXAMPLE — not Tarka morals.** Not a chargeback-guarantee SKU. Horizons never auto-demote a pack.

| Field | Notes |
|-------|-------|
| `schema_id` | `tarka.label_horizon/v1` |
| `example` | Always true: shipped numbers are examples, not product morals |
| `policy_owner` | `tenant` |
| `unit` | `days` |
| `by_kind.<label_kind>.window_days` | Positive integer (1–730) |

EXAMPLE defaults (buyers replace these):

| `label_kind` | EXAMPLE `window_days` | Typical use |
|--------------|----------------------:|-------------|
| `fp` | 7 | Frontline / promo FP days |
| `promo_abuse` | 14 | Promo FP / abuse window |
| `collusion` | 30 | Collusion window |
| `chargeback` | 90 | Card-scheme lag (~90d) |
| `fraud` | 90 | Same lag band as chargeback |
| `other` | 30 | Residual |

Wire: `decision_api.label_horizon.horizon_policy()` / `horizon_days(kind)`. Override with `TARKA_LABEL_HORIZON_JSON` (env wins) or desk_provision `label_horizons`. Unknown `label_kind` stays 422. Unknown override keys are ignored.

`labeled_at_by_trace` is persisted on late-label bind (time-to-first-label) so export / loop-metrics can join without a new plane.

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

## Optional consume → Observe draft

Buyer-owned. Joined warehouse labels since T (`labeled_at_by_trace`) may propose Observe drafts (`authored_by=seed`) via `consume_joined_labels`. `find_open_draft` keeps a second run from opening a duplicate. Promote only through existing gates / human. Never auto Active. Empty input = no drafts. Not a case inbox.

## Out of scope

- Changing bind implementation (W2)
- Hosting a warehouse
- Treating chargeback as the only label
- Chargeback-guarantee SKU
- CRM dispute product
- Auto-demote from horizons
- Consuming join-rate into Observe drafts (join-rate stays glass)
- Auto-Promote / auto Active from labels

Join-rate glass lives on `tarka.loop_metrics/v1` (`join_rate` / `labeled_receipt_rate`). See [bakeoff-metrics-v1](bakeoff-metrics-v1.md).
