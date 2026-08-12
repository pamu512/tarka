# Depth Fusion Implementation Plan

> Spec: `docs/superpowers/specs/2026-08-11-depth-fusion-design.md`

- [x] `depth_fusion.py` — co-occurrence heuristic
- [x] Wire in `depth_engines.py` + ops posture
- [x] Marketplace/food pack + typology bindings
- [x] Unit + golden tests

## Follow-on (B — sequence depth) shipped

- [x] Vertical sequence factors: cancel_after_pickup, rapid_cancel_refund, cancel_storm, chargeback_without_delivery, COD refuse, multi_refund, …
- [x] Typology predicates + food golden rows

## Follow-on (C — ring structure) shipped

- [x] Payment / place bridge differentiation + hubs
- [x] Promo→device→cross-role chain
- [x] Temporal edge age (fresh burst / stale velocity decay)
- [x] Typology predicates + marketplace golden rows + unit tests

## Follow-on (D — seller trajectory depth) shipped

- [x] `listing_burst` / `listing_to_payout_burst`
- [x] `ato_then_payout` / `ato_then_listing_burst` (host signals)
- [x] Typology predicates + marketplace golden rows + unit tests

## Follow-on (E — FTID / promo / representment + fusion recipes) shipped

- [x] FTID: multi-mismatch, item swap, serial returner, refund-over-value, instant-after-delivery
- [x] Promo: code-share farm, first-order max discount, geo/device redeem, refund-after-promo, employee stack
- [x] Representment: AVS/3DS dims, serial disputer, stale/early alert gaps, fraud-claim missing 3DS
- [x] Fusion pairs: ftid×representment, lifecycle×promo, promo×ftid, ring×ftid, trajectory×lifecycle, promo×representment, trajectory×representment, ring×representment, promo×trajectory
