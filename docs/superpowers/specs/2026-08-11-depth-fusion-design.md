# Cross-Engine Depth Fusion Design

> **Status:** Approved — 2026-08-11  
> **Parent:** [lifecycle-ring-depth-design](./2026-08-11-lifecycle-ring-depth-design.md)

## Goal

Detect multi-signal marketplace abuse: when lifecycle + ring (+ FTID/promo/trajectory/representment) co-occur on one evaluate, emit a **joint** depth score and host-actions — not independent flag stacking.

## Non-goals

- Forged LIVE / GNN claims
- Replacing child engines
- DIY device/brand signals

## Architecture

```text
lifecycle / ring / trajectory / ftid / promo / representment
                    │
                    ▼
            depth_fusion (co-occurrence)
                    │
                    ▼
     features + tags + capped score_delta + typology
```

## Schema

- `schema_id`: `tarka.depth_fusion/v1`
- `method`: `cooccurrence_heuristic_v1`
- `live_claim_allowed`: false
- `gnn_claim_allowed`: false

## Activation

An engine is **active** when its evidence exists and either:

- `score_0_100` / `risk_0_100` ≥ 40, or
- a hard flag is set (`lifecycle_risk_high`, `ring_score_high`, `cross_role_same_device`, `seller_trajectory_high`, `ftid_refund_hold`, `promo_econ_high`, `representment_weak`).

If fewer than **2** engines are active → return no fusion evidence (fail-soft).

## Pair recipes (detection)

| Pair | Factor code | Weight | Tags |
|------|-------------|--------|------|
| lifecycle × ring | `fusion:lifecycle_ring` | 28 | `action:hard_challenge`, `risk:collusion_refund_farm` |
| lifecycle × ftid | `fusion:lifecycle_ftid` | 30 | `action:refund_hold`, `risk:ftid` |
| ring × promo | `fusion:ring_promo` | 24 | `action:hard_challenge`, `risk:promo_farm` |
| trajectory × ftid | `fusion:trajectory_ftid` | 26 | `action:payout_hold`, `action:refund_hold` |
| lifecycle × representment | `fusion:lifecycle_representment` | 22 | `action:dispute_evidence_gap`, `risk:friendly_fraud` |
| ring × trajectory | `fusion:ring_trajectory` | 20 | `action:hard_challenge`, `risk:seller_collusion` |

Base fuse = sum of pair weights (cap 70) + optional lift `min(15, 0.08 * max_child_score)` when ≥3 engines active. Final `score_0_100` capped at 100.

## Outputs

- Features: `depth_fusion_score`, `depth_fusion_high` (≥45), `depth_fusion_active_count`, `fusion_factor:*`
- Rule hit: `depth_fusion_engine`
- Audit key: `depth_fusion`
- Score contribution: via existing depth merge cap (does not bypass 45 total depth ceiling)

## Pack / typology

- Marketplace (+ food) consume `depth_fusion_high`
- Typology `marketplace_depth_fusion` binds engine hit + factor predicates

## Success

- Golden: single-engine → no fusion; lifecycle+ring → fusion high + tags
- Honest paths stay fusion-absent
- Ops lists fusion in `GET /v1/ops/depth-engines`
