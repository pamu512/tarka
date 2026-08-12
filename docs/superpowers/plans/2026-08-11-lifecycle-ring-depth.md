# Lifecycle + Ring Depth Implementation Plan

> **PRIVATE / INTERNAL ONLY** — see RATING_PRIVACY.md  
> Spec: `docs/superpowers/specs/2026-08-11-lifecycle-ring-depth-design.md`

**Goal:** Ship computable OSS depth (sequence + structure) so LIVE feeds amplify the same interfaces to premium.

## Shipped (this session)

- [x] Design spec (lifecycle + ring, LIVE amplification map)
- [x] `lifecycle_risk.py` — transitions, time floors, amounts, stage signals, role clash
- [x] `ring_score.py` — UF components, cross-role bridges, pair velocity, promo hub, bipartite density
- [x] Evaluate wiring — features, score contribution, audit evidence, tags
- [x] Marketplace pack consumers (`mkt_lifecycle_risk_high`, `mkt_ring_score_high`)
- [x] Unit + combined tests

## Depth tracks wave 2 (shipped)

- [x] Seller trajectory changepoints — `seller_trajectory.py`
- [x] FTID causal FSM — `ftid_intake_gate.py` (mismatch taxonomy)
- [x] Promo economics fuse — `promo_economics.py`
- [x] Dispute representment strength — `dispute_representment.py`
- [x] Orchestrator — `depth_engines.py` + evaluate audit keys
- [x] Marketplace pack consumers for new `*_high` / hold flags

## Still open

- [x] Typology definitions that bind engine factor codes (not only pack booleans)
- [x] Golden JSONL corpora per vertical profile (lifecycle/ring/trajectory/ftid)
- [x] Ops surface: `GET /v1/ops/depth-engines` listing methods + schemas
