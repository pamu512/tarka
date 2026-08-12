# Order Lifecycle Risk + Multi-Party Ring Depth Design

> **PRIVATE / INTERNAL ONLY** — [`docs/compliance/RATING_PRIVACY.md`](../../compliance/RATING_PRIVACY.md)  
> **Status:** Approved direction (Approach A) — 2026-08-11  
> **Goal:** Best OSS multi-sided fraud core; LIVE feeds upgrade the same interfaces to premium (A+++ ops), not a rewrite.

## Problem

Surface packs (`boolean → score_delta`) and connector shells do not produce detection intelligence. Tarka must own **computable depth** offline: sequence risk over order lifecycles and structural collusion over role-labeled graphs. Vendors then amplify inputs; they do not replace the engines.

## Non-goals

- Forged LIVE / Motiva / Feast / GNN claims
- DIY device fingerprinting or brand crawl
- Re-homing loyalty multi-gate warehouse

## Architecture

```text
Host event trail + party graph (or graph-service edges)
        │
        ▼
┌───────────────────┐     ┌────────────────────┐
│ lifecycle_risk    │     │ ring_score         │
│ (sequence engine) │     │ (structure engine) │
└─────────┬─────────┘     └──────────┬─────────┘
          │                          │
          └──────────┬───────────────┘
                     ▼
            features + audit evidence
                     ▼
         typology / packs / host-actions
```

**LIVE premium path (same interfaces):** replace host-supplied device/place edges with Incognia/Fingerprint/SHIELD edges; inject face re-auth failures into ring nodes; keep engines unchanged. That is how OSS → A+++ without forking product logic.

---

## Engine 1 — Order lifecycle risk

### Input schema (`metadata.lifecycle` or `payload.lifecycle`)

```json
{
  "order_id": "o1",
  "currency": "USD",
  "events": [
    {"stage": "checkout", "ts": "2026-08-11T10:00:00Z", "amount": 40, "actor_role": "buyer"},
    {"stage": "paid", "ts": "...", "amount": 40, "actor_role": "buyer"},
    {"stage": "shipped", "ts": "...", "actor_role": "seller"},
    {"stage": "delivered", "ts": "...", "actor_role": "courier", "signals": {"pod_hash_ok": false}},
    {"stage": "refund_requested", "ts": "...", "amount": 40, "actor_role": "buyer"}
  ]
}
```

Canonical stages (ordered):  
`account_created` → `listing` → `checkout` → `paid` → `accepted` → `picked_up` → `shipped` → `out_for_delivery` → `delivered` → `cancelled` → `refund_requested` → `refund_approved` → `chargeback` → `payout`.

### Computations (deterministic)

1. **Illegal / suspicious transitions** — e.g. `refund_requested` before `delivered`/`picked_up`; `payout` before `delivered`; `chargeback` within minutes of `delivered`; `cancelled` after `delivered` without return stage.
2. **Time compression** — stage deltas below physical floors (checkout→delivered &lt; 2m food / &lt; 30m goods default; configurable per vertical profile).
3. **Amount path** — refund/chargeback amount ≥ paid; payout &gt; delivered value; discount stack where `paid << list`.
4. **Signal attachment** — `pod_hash_ok=false`, `intake_ok=false`, `gps_spoof=true` on stage events multiply stage weight.
5. **Role inconsistency** — same `actor_id` on buyer+seller or buyer+courier within one order trail.

### Output

```json
{
  "schema_id": "tarka.lifecycle_risk/v1",
  "score_0_100": 72.0,
  "driving_stage": "refund_requested",
  "factors": [{"code": "refund_before_delivery", "weight": 28, "detail": "..."}],
  "tags": ["risk:lifecycle", "action:refund_hold"],
  "vertical_profile": "marketplace_goods",
  "method": "sequence_heuristic_v1"
}
```

Score feeds `features.lifecycle_risk_score` and tags merge into evaluate.

---

## Engine 2 — Multi-party ring score

### Input schema (`metadata.party_graph` or `payload.party_graph`)

```json
{
  "nodes": [
    {"id": "u_buyer", "role": "buyer"},
    {"id": "u_seller", "role": "seller"},
    {"id": "d1", "role": "device"}
  ],
  "edges": [
    {"src": "u_buyer", "dst": "d1", "type": "USES_DEVICE", "weight": 1, "ts": "..."},
    {"src": "u_seller", "dst": "d1", "type": "USES_DEVICE", "weight": 1, "ts": "..."},
    {"src": "u_buyer", "dst": "u_seller", "type": "TRANSACTED", "count_24h": 8}
  ]
}
```

Roles: `buyer|seller|courier|driver|rider|device|place|promo`.

### Computations (deterministic, in-process; graph-service optional later)

1. Undirected connected components on device/place bridges.
2. **Cross-role device**: device node linked to ≥2 of {buyer,seller,courier,driver,rider}.
3. **Pair velocity**: `TRANSACTED` / `TRIPPED` edge `count_24h` above threshold.
4. **Bipartite density**: edges between complementary roles / component size.
5. **Promo hub**: promo node degree ≥ k to young buyers.

### Output

```json
{
  "schema_id": "tarka.ring_score/v1",
  "score_0_100": 81.0,
  "cross_role_same_device": true,
  "component_size": 4,
  "factors": [{"code": "cross_role_device", "weight": 34}],
  "members": ["u_buyer", "u_seller", "d1"],
  "tags": ["risk:collusion_shared_device", "action:hard_challenge"],
  "method": "heuristic_v1",
  "gnn_claim_allowed": false
}
```

---

## Evaluate integration

1. After marketplace/friendly-fraud feature hooks, run both engines if inputs present.
2. Merge tags; set numeric features for packs (`lifecycle_risk_score`, `ring_score`, `cross_role_same_device`).
3. Persist full evidence blocks on audit (`lifecycle_risk`, `ring_score`).
4. Fail-soft: missing trail/graph → no score (not zero-wash).

## Vertical profiles

| Profile | Time floors | Emphasized factors |
|---------|-------------|-------------------|
| `marketplace_goods` | checkout→delivered 30m | refund_before_delivery, FTID signals, seller-buyer device |
| `food_delivery` | checkout→delivered 2m | cancel_after_pickup, courier-buyer device, promo |
| `e_hailing` | request→complete 1m | driver-rider device, pair trip velocity |
| `last_mile` | — | COD refusal after accept, intake mismatch on refund |

## LIVE → A+++ mapping (same engines)

| OSS input | Premium LIVE substitution |
|-----------|---------------------------|
| Host `USES_DEVICE` edges | Fingerprint/Incognia device graph |
| Host `gps_spoof` on stage | Incognia/SHIELD place/spoof |
| Host `worker_auth_failed` node attr | Face/RTW connector |
| Host party graph dump | Graph-service + vendor writeback |
| Fixture labels for promote | Tenant y_labels from cases |

## Success criteria

- Lifecycle fixture suite: illegal transition, time compression, role clash, clean path
- Ring fixture suite: cross-role device, dense pair, honest disjoint
- Evaluate audit contains evidence with `method` + factor breakdown
- No LIVE env vars required for A-grade OSS depth
- Packs may *consume* scores; packs alone are not the depth

## Out of scope (next depth tracks)

Seller trajectory changepoints, FTID FSM taxonomy expansion, promo economics fuse, dispute representment strength — built on these two primitives.
