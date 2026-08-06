# Loyalty abuse model — upstream data prerequisites

**Status:** Prerequisite (not implemented as a closed economic model)  
**Date:** 2026-08-06  
**Design:** [loyalty-economics-multi-gate-design](../../superpowers/specs/2026-08-06-loyalty-economics-multi-gate-design.md) — hygiene feeds + program config + hybrid derive; independent gates **dispatch / redeem / order** (not checkout-only).  
**Related:** [graph-analysis](./graph-analysis.md), [competitive-score-matrix-2026-04](./competitive-score-matrix-2026-04.md), regrade canvas

## Why this exists

Graph linkage answers **who is related**. It does **not** answer whether a related cluster is **abusing loyalty**.

Effective assessment needs cluster economics, not signup location (often unavailable under Apple/Google/web privacy) and not relatedness alone.

## Model inputs (required)

| Parameter | Role |
| --- | --- |
| **Order velocity** | Burst order/redemption rate per account and per related cluster |
| **Churn / throwaway accounts** | Short-lived accounts, low repeat, high first-order promo take then abandon |
| **Total LTV** | Merchant contribution proxy for account/cluster (paid GMV − refunds − discounts, or agreed equivalent) |
| **Loyalty ÷ LTV** | Rewards/points/cashback as a share of LTV — abuse when loyalty extraction dominates contribution |

**Decision rule (product):** related + high velocity + churn pattern + high loyalty/LTV → loyalty abuse hypothesis. Related alone → insufficient.

**Gates (independent):** advice on **coupon dispatch**, **coupon redeem**, and **order benefit eligibility** — not a single flag; not all need be true together; never deny the purchase via this path alone.

## Upstream data prerequisites (hard)

The model **cannot work effectively** without tenant-supplied (or warehouse-joined) baselines. Mark these as **integration prerequisites**, not optional enrichments:

| Upstream feed | Needed to compute |
| --- | --- |
| Orders / checkouts (entity_id, timestamps, amounts, status) | Order velocity, LTV basis |
| Refunds / chargebacks / cancellations | Net LTV |
| Loyalty ledger (points earned/burned, cashback, coupon face value) | Loyalty cost |
| Account lifecycle (created_at, last_active, closed/churn flags) | Churn cohorts |
| Graph / entity links (device, payment, referral — already in-platform when graph on) | Related cluster membership |

**Baselines:** per-tenant or per-program normals (e.g. p50/p90 order velocity, typical loyalty/LTV %) so scores are relative, not absolute guesses.

### Feed snapshot example (Layer 1)

Evaluate ingress uses `metadata.loyalty_feed_snapshot`. A field-complete snapshot declares `feeds_present[]`, `feeds_complete`, and `as_of` (freshness checked against `max_feed_age_seconds` in program config):

```json
{
  "as_of": "2026-08-06T12:00:00Z",
  "feeds_present": ["orders", "refunds", "loyalty_ledger", "lifecycle"],
  "feeds_complete": true,
  "orders": [
    {
      "entity_id": "e1",
      "order_id": "o1",
      "ts": "2026-08-06T12:00:00Z",
      "amount_minor": 1000,
      "currency": "USD",
      "status": "paid"
    }
  ],
  "refunds": [],
  "loyalty_ledger": [
    {
      "entity_id": "e1",
      "ts": "2026-08-06T12:00:00Z",
      "direction": "burn",
      "value_minor": 400,
      "program_id": "default"
    }
  ],
  "lifecycle": [
    {
      "entity_id": "e1",
      "created_at": "2025-01-01T00:00:00Z",
      "last_active_at": "2026-08-06T12:00:00Z"
    }
  ]
}
```

Missing refunds while orders present, or missing ledger, → `feeds_incomplete` (never `eligible: true`).

### Program config example (Layer 2)

See [`rules/loyalty_program_config.example.json`](../../../rules/loyalty_program_config.example.json). Ingress key: `metadata.loyalty_program_config`.

### Multi-gate output status

Engine output schema: `tarka.loyalty_economics_gates/v1`. Full gate vector contract (dispatch / redeem / order independence, metrics, hysteresis): [loyalty-economics-multi-gate-design § Multi-gate output contract](../../superpowers/specs/2026-08-06-loyalty-economics-multi-gate-design.md#multi-gate-output-contract).

| Condition | `status` | Gate `eligible` |
| --- | --- | --- |
| No/partial hygiene feeds | `feeds_missing` / `feeds_incomplete` | `null` |
| No program config | `config_missing` | `null` |
| Snapshot older than SLA | `stale` | `null` |
| Layer 1+2 ok, no spend feeds | `ok` or `partial_derived` | computed from Layer 2 thresholds |
| Graph unavailable | `ok` with `unit=entity` | computed; reasons note `graph_unavailable` |

`eligible` is `true` or `false` only when that gate’s `status` is `ok`. Hygiene/config failures must not imply eligible. Order gate advice never denies purchase (`order_decision_untouched: true`).

## Current gap (honest)

| Piece | Status |
| --- | --- |
| Graph related accounts | Available when `GRAPH_SERVICE_URL` set |
| Generic event velocity | Partial (counters / inference velocity) |
| Promo redemption dashboards | Partial / demo-adjacent |
| Cluster LTV + loyalty÷LTV + churn economics | **Missing** — prerequisite not met |

Until upstream feeds and baselines exist, do **not** claim an effective loyalty-abuse model on related accounts. Treat Inference / Fraud Ops stretch for loyalty vertical as **blocked on this prerequisite**.

## Claim language

- **OK:** “Graph links related accounts; loyalty-abuse economics require order/LTV/loyalty upstream.”
- **Not OK:** “Model detects loyalty abuse on related accounts” without the four parameters and baselines.
