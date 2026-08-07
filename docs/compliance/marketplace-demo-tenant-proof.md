# Marketplace demo tenant proof (`mkt-demo-2026`)

**Schema:** `tarka.marketplace_demo_tenant_proof/v1`  
**Smoke:** `python3 scripts/oss/marketplace_demo_tenant_proof.py`

## What this proves

| Surface | Evidence |
|---|---|
| Durable payout board | ≥2 `source=durable` holds for `mkt-demo-2026` |
| Durable promo board | ≥2 redemptions on shared coupon/device |
| Durable seller board | ≥2 seller integrity rows |
| Collusion roles | `map_labels_to_roles` → buyer/seller/courier |
| Measured FPR | Labeled fixture holds; FPR ≤ 0.25 |

## Honesty

- Named **demo** tenant fixture — not a live production outcome pack.
- Does **not** start L3 ops ledger.
- Does **not** satisfy L2 LIVE partner fusion (still WAIVED without vendor credentials).
