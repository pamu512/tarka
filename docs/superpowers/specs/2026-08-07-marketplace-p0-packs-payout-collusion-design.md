# Marketplace / q-comm / logistics / food — P0 design

**Date:** 2026-08-07  
**Branch base:** `maturity-4-0-local`  
**Status:** Implemented (2026-08-07) · plan: `docs/superpowers/plans/2026-08-07-marketplace-p0-packs-payout-collusion.md`  
**Canvas:** marketplace-delivery landscape P0 (packs → payout → collusion rail)

> **PRIVATE / INTERNAL ONLY — ratings & gradings.**  
> Policy: [`docs/compliance/RATING_PRIVACY.md`](../../compliance/RATING_PRIVACY.md).

## Goal

Ship three production-grade slices for multi-party platforms (marketplaces, quick commerce, logistics, food delivery):

1. **Vertical rule packs** with real install/promote/kill gates  
2. **Pre-payout control** driven by evaluate tags into a durable hold store + webhooks  
3. **Multi-party collusion rail** on CaseDetail backed by a real API (graph neighbors + role + linked cases)

## Non-negotiables

- **No stubs, placeholders, or “thin” demo paths** for any new surface. If payout holds are developed, they are durable and attributable. If the collusion rail is developed, it is API-backed with tests, not client-only label paint.
- Existing `payout_delay_automation.py` **demo_aggregate** generator must be **replaced or subordinated**: list endpoint returns durable holds (plus optional seed for empty tenants in tests only — never as the sole production behavior).
- Reuse install/promote/kill patterns in `rule_api.py` / `vertical_packs.py`. Do not invent a parallel pack system.
- Location remains **partner enrichment**; collusion relatedness is **graph + rules**, not GPS-as-linker.
- Ratings/grades stay private; do not add public maturity claims.

## Out of scope

- Live Incognia/Fingerprint tenant proof (use fusion tags when present; do not forge LIVE pins)  
- Live loyalty warehouse DB (promo rules may use features; feeds remain separate)  
- Chargeback guarantee product  
- New graph database product  
- Full GrabDefence device SDK

---

## Slice 1 — Vertical packs (full)

### Files

- `services/decision-api/src/decision_api/vertical_packs.py` — add four packs  
- Tests: extend `test_api_endpoints.py` / `test_kill_criteria_promote_gate.py` (or dedicated `test_marketplace_vertical_packs.py`)  
- Docs: short guide `docs/docs/guides/vertical-packs-marketplace-delivery.md` (install + tag contract + pre-payout)

### Packs

| Pack id | Name | Abuse focus |
| --- | --- | --- |
| `marketplace` | Vertical Marketplace | seller–buyer collusion, refund burst, review inflation, pre-payout hold |
| `qcommerce` | Vertical Quick Commerce | promo/referral farm, multi-account velocity, rider bonus spoof tags |
| `logistics` | Vertical Logistics | multi-account partner/driver, order hogging velocity, payout hold |
| `food_delivery` | Vertical Food Delivery | diner–courier–merchant triangle, cancellation/refund abuse, courier spoof |

### Rule quality bar

Each pack **≥ 5 rules** with:

- Realistic `when` clauses on existing/evaluate-friendly fields (amount, velocity counters, `is_emulator`, `is_bot`, account_age_days, distinct device/entity features when available, tag presence for vendor spoof)  
- Tags including `vertical:<pack>` plus at least one of:  
  `risk:collusion_shared_device`, `risk:promo_farm`, `risk:courier_spoof`, `risk:refund_burst`, `risk:multi_account_partner`, `action:payout_hold`, `action:payout_delay`  
- Non-zero `score_delta` and human `description`  
- Shared `standard` velocity presets + pack-specific `kill_criteria` (same shape as fintech)

### Acceptance

- `GET /v1/rules/vertical-packs` lists all four  
- Install and promote refuse on kill_criteria failure (409) for each pack name  
- Install succeeds with healthy metrics; rules load and appear in rule listing  
- Benchmark/smoke can target new vertical names where vertical benchmark already keys off pack name

---

## Slice 2 — Pre-payout (full, durable)

### Product moment

**Pre-payout checkpoint** = `POST /v1/evaluate` (or existing evaluate path) with:

- `event_type` / metadata indicating payout (canonical: `metadata.checkpoint = "payout"` or `event_type = "payout"`)  
- Entity = payee (seller / courier / partner)  
- Optional `metadata.payout_id`, `amount`

When resulting decision `tags` include `action:payout_hold` or `action:payout_delay`, the platform **creates or updates a durable payout hold**.

### Architecture

```
evaluate (decision-api)
  → tags include action:payout_hold | action:payout_delay
  → persist hold via integration-ingress internal API (or shared store)
  → optional marketplace webhook (block/hold signal)
  → Ops payout-delay UI lists durable holds (not demo RNG rows)
```

### Durable hold model (production)

Replace demo-only list as source of truth. Persist holds with at least:

| Field | Purpose |
| --- | --- |
| `tenant_id`, `payout_id`, `entity_id` | Identity |
| `status` | `held` \| `released` \| `pending` |
| `hold_reason` | e.g. `tag:action:payout_hold` or mule threshold |
| `held_by` | `evaluate` \| `payout_delay_automation` \| `analyst` |
| `decision_id` / `trace_id` | Attribution to evaluate |
| `tags` | Snapshot of triggering tags |
| `amount`, `currency` | Optional from metadata |
| `held_at`, `scheduled_release_at`, `released_at` | Lifecycle |
| `mule_score` | Optional; keep Janus threshold path as **additional** trigger |

Storage: Postgres table in integration-ingress (or case-api if that is the established ops DB) — **not** process-local dicts as sole store. In-memory overlay allowed only as cache on top of durable rows.

### APIs

1. **Internal/create from decision** — called from decision-api after evaluate when payout checkpoint + action tags (HTTP to ingress or shared library). Fail closed: log + metric if hold write fails; evaluate still returns decision.  
2. **`GET` payout-delay list** — returns durable holds + config; mule-threshold automation may still create holds when graph mule_score ≥ threshold (real write, not synthetic).  
3. **`POST` release** — analyst release; audit fields.  
4. **Webhook** — reuse marketplace webhook log path to notify client of hold/release when configured.

### Config

Extend tenant config:

- `automation_enabled`  
- `mule_score_hold_threshold`  
- `honor_evaluate_action_tags` (default **true**)  
- `hold_duration_hours_default`  
- `delay_hours_for_action_payout_delay` (shorter than full hold if distinct)

### Acceptance

- Evaluate with `checkpoint=payout` + pack rules firing `action:payout_hold` → hold row exists after call  
- List endpoint returns that row after process restart (durable)  
- Release clears hold; webhook log entry when callback configured  
- Mule-threshold path still can hold without evaluate tags  
- Pytest covers create/list/release; no reliance on `source: demo_aggregate` for the happy path  
- OpenAPI / guide documents the pre-payout checkpoint contract

---

## Slice 3 — Multi-party collusion rail (full)

### Product

CaseDetail **Multi-party links** panel: neighbors of the case entity with **role**, **path**, **propagated risk**, and **linked open/closed cases**.

### API (case-api)

`GET /v1/cases/{case_id}/multi-party-links?depth=3`

Response shape (normative):

```json
{
  "case_id": "...",
  "entity_id": "...",
  "tenant_id": "...",
  "links": [
    {
      "entity_id": "...",
      "roles": ["courier"],
      "distance": 1,
      "propagated_risk_score": 0.42,
      "path_description": "...",
      "shared_signals": ["device", "payment"],
      "cases": [
        {"case_id": "...", "status": "RESOLVED_FRAUD", "disposition_reason": "..."}
      ]
    }
  ]
}
```

### Behavior

1. Load case → `entity_id`, `tenant_id`  
2. Call graph `risk_propagation` (existing)  
3. Map `entity_labels` → roles via deterministic mapper (`Buyer`/`Consumer`/`Diner` → buyer; `Seller`/`Merchant` → seller; `Courier`/`Driver`/`Partner` → courier; else `unknown`)  
4. For each neighbor entity_id, query cases for that tenant+entity (list/filter — add query param on list_cases if missing: `entity_id=`)  
5. Optional: extract shared edge types into `shared_signals` when path/rel_types available  
6. Return stable sort: distance asc, risk desc  

### Frontend

- New panel/component on CaseDetail (desktop rail + mobile section)  
- Loading / empty / error states  
- Links to Graph Explorer and CaseDetail for linked cases  
- Roles shown as chips; do not invent roles client-side beyond API  

### Fixture / tests

- Graph fixture or mocked risk_propagation returning three roles on one device path  
- Case-api test: multi-party-links joins cases by entity_id  
- Frontend unit/component test for rendering roles + case links  

### Acceptance

- Analyst opens case B; rail shows A’s entity with role + prior disposition when data exists  
- Endpoint 404s cleanly for missing case; 502/degraded message if graph down (no silent empty success without `degraded` flag)

---

## Implementation order

1. Slice 1 packs + tests + guide  
2. Slice 2 durable holds + evaluate bridge + webhook + retire demo-as-source-of-truth  
3. Slice 3 multi-party API + CaseDetail UI + tests  

Each slice merges only when its acceptance checks pass.

## Verification suite (program)

```bash
# decision-api
pytest services/decision-api/tests/test_marketplace_vertical_packs.py \
  services/decision-api/tests/test_payout_hold_from_evaluate.py -q

# integration-ingress
pytest services/integration-ingress/tests/test_payout_delay_durable.py -q

# case-api
pytest services/case-api/tests/test_multi_party_links.py -q

# frontend (targeted)
npm test -- --run multiPartyLinks  # or project’s equivalent
```

Exact filenames may adjust in the plan; coverage must match acceptance above.

## Risks

| Risk | Mitigation |
| --- | --- |
| Demo payout UI consumers break | Keep response shape; change `source` to `durable` / `durable+automation`; document |
| Evaluate latency if sync hold write | Short timeout + async queue fallback with durable intent log |
| Graph labels sparse | Role `unknown` + still show entity + cases; document label conventions for ingest |

## Success

- Four vertical packs installable under kill gates  
- Pre-payout evaluate creates durable holds and notifies webhooks  
- CaseDetail multi-party rail is API-complete with roles and linked cases  
- No stub/TODO/demo-only source of truth for these three surfaces  

---

## Appendix A — Reuse inventory (offline / refund / loyalty / marketplace)

Research date: 2026-08-07. Prefer reuse over rewrite; do **not** re-home loyalty economics into Tarka.

### A.1 Sibling repo: `loyalty-abuse` (canonical for promo / LTV gates)

Path: `/Users/pamu/Documents/GitHub/loyalty-abuse` (removed from Tarka in `9f6fd7a1`).

| Asset | Reuse for P0 |
| --- | --- |
| `src/loyalty_abuse/multi_gate.py` (`evaluate_loyalty_economics`) | **Do not copy back.** Call via HTTP/adapter for q-comm / food **promo & redeem** checkpoints; packs emit tags that *complement* friction, not replace LTV gates |
| `src/loyalty_abuse/warehouse.py` + feed contracts | Warehouse/snapshot shape for promo rules that need `orders` / `refunds` / `loyalty_ledger` / `lifecycle` |
| Typologies: `partner_promo_farm`, `multi_account`, `trial_referral_farm`, `promo_stack`, `return_to_points` (refund→points→reburn), `bot_redeem`, `referral_self_deal` | Steal **feature names + reason codes** into vertical pack `when` fields / tag vocabulary |
| `adapters/tarka/` | Prefer extending this adapter over duplicating scorer inside decision-api |
| Contracts: `evaluate-request.schema.json`, `loyalty_program_config.example.json` | Align Tarka `metadata` for redeem/dispatch events |

**Product rule (already locked):** graph relatedness ≠ loyalty abuse. Loyalty abuse stays in `loyalty-abuse`; Tarka owns graph + payout + cases.

### A.2 Tarka marketplace ingress (reuse UI + APIs; upgrade demo cores)

| Module | Status today | P0 reuse |
| --- | --- | --- |
| `integration_ingress/promo_abuse_tracking.py` + `PromoAbuseDashboard` | **Demo synthetic** redemptions (`shared_device_cluster` flags) | Keep dashboard route; **replace payload builder** with durable redeem events or loyalty-abuse analytics summary — do not ship packs that only paint this demo |
| `integration_ingress/seller_integrity.py` + `SellerIntegrityDashboard` | **Demo** review/delivery ratios + scoring heuristics | Reuse **scoring function** (`_score_seller`, ratio thresholds) in marketplace pack rules / features; upgrade data source to real deliveries/reviews when wiring |
| `integration_ingress/payout_delay_automation.py` + `PayoutDelayAutomation` | **Demo RNG** payouts + in-memory release set | **Slice 2 target:** durable holds; keep REST paths (`GET/PATCH/release`) and UI |
| Marketplace SDK keys, rate-limit shields, webhook logs | Real-ish ingress product | Reuse webhooks for hold/release notifications |

### A.3 Refund / dispute / friendly-fraud (reuse for refund-abuse rules)

| Module | Status | P0 reuse |
| --- | --- | --- |
| `case_api/dispute_api.py` | Production disputes (`chargeback`, `fraud_claim`, `product_not_received`, …) + outcomes | Link collusion rail / packs to dispute outcomes; `y_label` / disposition join already exists |
| `shadow_agent/friendly_fraud.py` | **Real heuristics:** POD hash alignment vs dispute time; same-IP order history from `AuditLog` | Reuse for `risk:refund_burst` / friendly-fraud tags in **food_delivery** + **marketplace** packs; call or port feature extractors into evaluate features |
| `orchestrator/disputes/*`, `dispute_evidence_pdf.py`, `shadow_agent/dispute_letter.py` | Representment / evidence tooling | Out of P0 critical path; optional later for diligence export |
| `tools/shadow/.../chargeback.py`, `promo_abuse.py`, `collusion.py` | **Stubs only** | Do **not** build on these stubs |

### A.4 Offline (counters / features — not “offline payments”)

| Module | Meaning | P0 reuse |
| --- | --- | --- |
| `scripts/replay/run_offline_parity.py`, `run_audit_offline_parity.py`, counter dual_diff CI | Online/offline **counter** parity | Use for velocity features packs depend on (`event_count_*`); not a payment-offline product |
| `services/batch-ingest` → ClickHouse `fraud_features_offline` | Historical feature backfill | Optional training/bench data for vertical pack sim |
| ClickHouse “offline” in decision-api config | Analytics fail-closed when CH down | Unrelated to marketplace offline mode |

If the user meant **offline / cash-on-delivery / store pickup** abuse: **no dedicated module found** — add pack rules + features in P0 only if ICP requires it (new scope).

### A.5 Graph / relatedness / labels (reuse for collusion rail)

| Module | P0 reuse |
| --- | --- |
| `relatedness_evidence.py` + `relatedness_evidence_smoke.py` | Audit snapshot tags (`sdk:shared_device`, copresence) — pack `when` on tags |
| Graph `risk_propagation` | Slice 3 multi-party links core |
| `y_label_store.py`, `label_join.py`, disposition → labels | Prior case outcomes on collusion rail; kill_criteria metrics |
| `partner_fusion.py` | Courier spoof tags (`vendor:incognia*`) into logistics/food packs — fuse, don’t rebuild |

### A.6 Spec implications (full-feature, no rebuild)

1. **Slice 1 packs:** Import tag/feature vocabulary from `loyalty-abuse` typologies + seller_integrity thresholds + friendly_fraud signals; keep LTV multi-gate **out of** Tarka.  
2. **Slice 2 payout:** Upgrade existing payout-delay **API/UI**; kill `demo_aggregate` as source of truth.  
3. **Slice 3 collusion:** Build on `risk_propagation` + case list-by-entity; ignore shadow `collusion.py` stubs.  
4. **Promo dashboard:** Either wire to durable events or to `loyalty-abuse` analytics — do not treat current promo_abuse_tracking demo as done.  
5. **Optional follow-on (not P0 unless approved):** COD/offline-payment pack; HTTP client from decision-api → `loyalty-abuse` `/v1/evaluate` at redeem checkpoint.
