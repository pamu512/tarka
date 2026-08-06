# Loyalty Economics Multi-Gate Design

**Date:** 2026-08-06  
**Status:** Approved for planning  
**Closes (partial):** Missed-mark C1/C3/S9 — related ≠ abuse; upstream hygiene + economics  
**Does not close:** Live L2 partner pin, L3 four-week ops, location reweight (separate)  
**Related:** [loyalty-abuse-model-prerequisites.md](../../docs/guides/loyalty-abuse-model-prerequisites.md), critical regrade canvas

## Goal

Ship a **shadow** loyalty-economics path that:

1. Treats **upstream feed contracts as basic data hygiene prerequisites** (not optional enrichment).
2. Uses **tenant program economics config** for thresholds (CAC, retention, loyalty÷LTV, ROI).
3. Is shaped for **hybrid derive** later (spend/acquisition feeds refine CAC/retention/ROI).
4. Emits **independent multi-level gates** — dispatch / redeem / order eligibility — not a single checkout boolean.
5. **Never denies the order** via this path; it only advises benefit/coupon suppression or allow.

## Non-goals (v1)

- Blocking purchase (`deny` / platform `block`) from loyalty economics alone.
- Native location-as-linker for relatedness (graph + economics; location out of this path).
- Full CRM/ESP integration — we define the **advice contract**; hosts enforce.
- Auto-derived CAC without spend feeds (config required; derive is layer-3 optional).

---

## Hard constraints (from failure analysis)

| ID | Constraint |
| --- | --- |
| H1 | Field-complete hygiene gate; **no** `eligible: true` on partial or stale feeds |
| H2 | Explicit account vs cluster application + household/VIP escape hooks |
| H3 | Locked time windows + LTV / loyalty-cost definitions in the contract |
| H4 | Hysteresis + min dwell in band (anti-thrash restore) |
| H5 | Host benefit-suppression contract separate from order decision |
| H6 | Program config versioning (`effective_at`, change audit) |
| H7 | Graph-optional degraded mode named honestly (single-entity if no graph) |
| H8 | This signal **must not** be usable as a deny predicate without a separate product decision |
| H9 | **Three independent gates** — dispatch, redeem, order — not all required true together |
| H10 | Scope per evaluation: `program` \| `coupon_id` \| `offer_class` (earn / burn / partner) |

---

## Architecture — three layers (all in the design)

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1 — Hygiene feeds (PREREQUISITE)                          │
│ orders · refunds/cancels · loyalty ledger · account lifecycle   │
│ optional: marketing/acquisition spend (enables Layer 3 derive)  │
└────────────────────────────┬────────────────────────────────────┘
                             │ field-complete + freshness SLA
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2 — Tenant program config (PREREQUISITE for thresholds)   │
│ CAC · retention_cost · target_loyalty_ltv_ratio                 │
│ ineligible_above · restore_at_or_below · dwell · target_ROI     │
│ config_version · effective_at                                   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3 — Optional derive (hybrid)                              │
│ spend feeds → refined CAC / retention / program ROI             │
│ if absent: status partial_derived; use Layer 2 point estimates  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ loyalty_economics engine (pure)                                 │
│ cluster|entity rollup → velocity, churn, LTV, loyalty÷LTV, ROI  │
│ → gate vector: dispatch / redeem / order                        │
└────────────────────────────┬────────────────────────────────────┘
                             │ shadow audit + tags only
                             ▼
                    Host systems (CRM, loyalty, checkout)
```

**v1 implement:** Layers 1–2 required for `status=ok`; Layer 3 optional.  
**v1 evaluate hook:** shadow advice only (Approach A).

---

## Upstream hygiene contract (Layer 1)

Spelled out as **basic data hygiene** — model ineffective without them.

| Feed | Min fields (normative) | Used for |
| --- | --- | --- |
| **Orders** | `entity_id`, `order_id`, `ts`, `amount_minor`, `currency`, `status` | Velocity, LTV basis |
| **Refunds/cancels** | `entity_id`, `order_id`, `ts`, `amount_minor`, `currency` | Net LTV |
| **Loyalty ledger** | `entity_id`, `ts`, `direction` (earn\|burn), `value_minor` or points+rate, `program_id`, optional `coupon_id` | Loyalty cost |
| **Lifecycle** | `entity_id`, `created_at`, `last_active_at`, optional `churned_at` / status | Churn proxy |
| **Spend (optional L3)** | `ts`, `channel`, `cost_minor`, `currency`, cohort keys | Derived CAC/retention |

**Completeness rules:**

- Snapshot must declare `feeds_present[]` and `feeds_complete: bool`.
- Missing refunds while orders present → **incomplete** (inflated LTV risk).
- Missing ledger → **incomplete** (cannot compute loyalty÷LTV).
- `as_of` + `max_age_seconds`; exceeded → `status=stale` (not ok).

**Identity:** join key contract `entity_id` ↔ loyalty member id ↔ order customer id documented; broken join → incomplete, not silent zero.

---

## Program config (Layer 2)

Per `tenant_id` + `program_id`:

| Field | Meaning |
| --- | --- |
| `acquisition_cost_minor` | CAC baseline (tenant-supplied v1) |
| `retention_cost_minor` | Retention cost baseline for window |
| `target_loyalty_ltv_ratio` | Healthy loyalty cost / LTV |
| `ineligible_above_ratio` | Breach → gate(s) may flip ineligible |
| `restore_at_or_below_ratio` | Restore band (≤; hysteresis) |
| `min_dwell_seconds` | Must stay in restore band this long before eligible again |
| `target_program_roi` | Optional; loyalty cost vs contribution |
| `window` | Locked semantics e.g. `trailing_90d` for ratio; velocity window separate |
| `new_member_grace_days` | Exclude or relax ratio for tenure &lt; N |
| `vip_entity_ids` / `allowlist_ref` | Escape hatch |
| `config_version`, `effective_at` | H6 |

---

## Multi-gate output contract

Not one boolean. Independent gates:

```json
{
  "schema_id": "tarka.loyalty_economics_gates/v1",
  "status": "ok | feeds_missing | feeds_incomplete | config_missing | stale | partial_derived",
  "unit": "cluster | entity",
  "cluster_id": "...",
  "entity_id": "...",
  "scope": { "kind": "program | coupon_id | offer_class", "id": "..." },
  "as_of": "ISO-8601",
  "metrics": {
    "order_velocity": {},
    "churn_proxy": {},
    "ltv_minor": 0,
    "loyalty_cost_minor": 0,
    "loyalty_ltv_ratio": 0.0,
    "program_roi": null,
    "window": "trailing_90d"
  },
  "gates": {
    "dispatch": {
      "eligible": null,
      "status": "ok | skipped | feeds_incomplete | ...",
      "reasons": [],
      "as_of": "..."
    },
    "redeem": { "eligible": null, "status": "...", "reasons": [], "as_of": "..." },
    "order": { "eligible": null, "status": "...", "reasons": [], "as_of": "..." }
  },
  "policy": {
    "config_version": "1",
    "hysteresis": {},
    "order_decision_untouched": true
  }
}
```

### Gate semantics

| Gate | Advice meaning | Host typically |
| --- | --- | --- |
| **dispatch** | Should we **send** this coupon/offer? | CRM / ESP / loyalty inbox |
| **redeem** | May user **claim/attach** this instrument? | Loyalty wallet / code claim |
| **order** | May **this order** apply loyalty/coupon benefits? | Checkout / tender / post-purchase grant |

- `eligible` is `true` \| `false` only when that gate’s `status` is `ok` (or explicit policy `forced_*`).
- On hygiene/config failure: `eligible: null`, gate `status` explains — **never** imply eligible.
- Order gate **false** ⇒ suppress benefits on that order; purchase decision remains outside this module (`order_decision_untouched: true`).
- Policies may weight metrics differently per gate (e.g. dispatch heavier on churn; order heavier on loyalty÷LTV; redeem heavier on instrument caps + ratio).

### Independence examples

- Dispatch no → redeem/order N/A for that unsent offer.
- Dispatch yes, redeem no → offer visible/sent but cannot claim.
- Dispatch + redeem yes, order no → instrument in wallet; this basket cannot use it.
- Base earn order-eligible while a specific coupon fails redeem (scope = `coupon_id`).

---

## Evaluate / API integration (v1 shadow)

1. **Pure module** `loyalty_economics.py` — no I/O; inputs = feed snapshot + config + optional graph cluster ids.
2. **Ingress:** feed snapshot + config via evaluate `metadata` and/or internal store keyed by tenant/program (implementation plan chooses one primary; both allowed).
3. **Pipeline:** after graph risk (for cluster id when present); compute gates; attach to `payload_snapshot.loyalty_economics_gates` and `inference_context`.
4. **Tags (advisory):** e.g. `loyalty:dispatch_ineligible`, `loyalty:redeem_ineligible`, `loyalty:order_benefit_ineligible` — only when gate status ok and eligible false.
5. **Enforcement:** do **not** map these tags to `deny` / `block` in v1 (H8). Host loyalty/checkout consumes advice.
6. **Shadow flag:** respect existing shadow evaluate — no mutating host side effects from this module.

---

## Restore / hysteresis

- Ineligible while `loyalty_ltv_ratio > ineligible_above_ratio` (and optional ROI breach), subject to grace/VIP.
- Restore only when ratio `≤ restore_at_or_below_ratio` for `min_dwell_seconds` continuously (per gate state store or snapshot history).
- Per-gate state machines may diverge (dispatch restored, redeem still cooling).

---

## Error / degrade matrix

| Condition | `status` | Gate `eligible` |
| --- | --- | --- |
| No/partial hygiene feeds | `feeds_missing` / `feeds_incomplete` | `null` |
| No program config | `config_missing` | `null` |
| Snapshot older than SLA | `stale` | `null` |
| Layer 1+2 ok, no spend feeds | `ok` or `partial_derived` | computed from Layer 2 CAC/retention |
| Graph unavailable | `ok` with `unit=entity` | computed; reasons note `graph_unavailable` |

---

## Testing (success criteria)

1. Unit: ratio breach → order gate ineligible; decision path still allow when only loyalty economics fires.
2. Unit: incomplete refunds → no eligible true.
3. Unit: hysteresis — brief dip below restore threshold does not flip eligible without dwell.
4. Unit: dispatch ineligible + order eligible possible under different policy weights/fixtures.
5. Contract test: evaluate audit contains `loyalty_economics_gates` schema; no deny from module alone.
6. Docs: prerequisites guide updated to multi-gate + three layers.

---

## Claim language

- **OK:** “Shadow multi-gate loyalty economics advice (dispatch / redeem / order); requires hygiene feeds + program config.”
- **Not OK:** “Detects loyalty abuse” or “Blocks abusers at checkout” without S9 feeds and host enforcement.

---

## Implementation sketch (for planning; not committed until plan)

| Piece | Location |
| --- | --- |
| Schemas / examples | `docs/docs/guides/loyalty-abuse-model-prerequisites.md` + JSON schema under `services/decision-api/...` or `rules/` |
| Engine | `services/decision-api/src/decision_api/loyalty_economics.py` |
| Tests | `services/decision-api/tests/test_loyalty_economics_gates.py` |
| Pipeline hook | `evaluate/pipeline.py` (shadow-safe, non-deny) |
| Config load | tenant file or metadata — plan picks minimal path |

---

## Spec self-review

- [x] No placeholder APIs without status enum  
- [x] H1–H10 mapped into contract  
- [x] Multi-gate independence explicit  
- [x] Order non-deny explicit  
- [x] Layer 3 hybrid shaped without blocking v1  
- [x] Scope ambiguity (account vs cluster) called out — plan must pick default: **cluster when graph peers ≥1 else entity**  
- [x] Out of scope: CRM connectors, live L2 location  

**Open for plan (not blockers for this design):** exact store for feed snapshots; per-gate policy weight defaults; whether redeem checks instrument caps in v1 or host-only.
