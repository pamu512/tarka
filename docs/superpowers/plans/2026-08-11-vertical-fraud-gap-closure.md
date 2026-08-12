# Vertical Fraud Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the market-research gaps for marketplaces, food delivery / q-commerce, last-mile logistics, and e-hailing by shipping Tarka-native features from OSS + local toolkits, and production-ready vendor connectors where the category leader or consortium data wins.

**Architecture:** Tarka remains the evaluate → typology → graph → case/dispute OS. Specialist scorers (`loyalty-abuse`, `refund-abuse-risk`, `offline-cancel-risk`) become first-class bridges with honesty posture. Industry-leading device, KYC/KYB, chargeback-alert, face/RTW, and brand-protection capabilities are **connectors** (live credentials, fail-closed, contract tests)—not reimplemented. OSS (Marble continuous-screening patterns, Tazama typology fleet shapes, Ojuri promote science, Osprey/CEL typology packs, OpenSanctions/yente, Feast contract honesty, DGFraud/AWS GNN *patterns*) informs packs and control planes inside Tarka.

**Tech Stack:** Existing Tarka decision-api / graph-service / case-api / integration-ingress; sibling toolkits under adapters; vendor plugins following `vendors/plugins/{fingerprint,incognia,opensanctions}.py` pattern; typology JSON + predicate registry; diligence/CLAIM_LOCK honesty gates unchanged (no forged LIVE).

## Global Constraints

- No forged LIVE partner pins, Motiva claims, Feast-class claims, or L3 COMPLETE without evidence.
- Loyalty multi-gate warehouse stays in `loyalty-abuse` (do not re-home); Tarka bridges + feed posture only.
- `scripts/oss/shadow_four_week_sim.py` must never advance the L3 ledger.
- Connector principle: if detection quality requires consortium graphs or a category-defining vendor (device integrity, face/RTW, chargeback alerts, identity KYB), ship **production connector** (auth, retries, circuit, evidence tags, ops posture, contract tests)—do not DIY the core signal.
- OSS/build principle: policy packs, typology control plane, graph relatedness, evaluate bridges, refund/cancel scoring composition, promote science, local-rail playbooks → build in Tarka (or thin adapter to sibling toolkit).
- Bleeding-edge allowed behind stable interfaces (plugin + posture + fail-closed).

## Detection-policy questions (answer before / during Wave 0)

These change *what* we detect and enforce—not how we implement. Defaults below apply until overridden.

| # | Question | Locked answer (2026-08-11) | Why |
|---|----------|------------------------------|-----|
| Q1 | Priority order | **Marketplace-first** → food → e-hailing → last-mile (user: best OSS for marketplace fraud) | Competitive target |
| Q2 | Same-device cross-role | Score + hard_challenge floor; suspend after repeat/cluster threshold | Default |
| Q3 | Refund path | Advisory + optional host-action; Downstream owns money unless tenant opts in | Default |
| Q4 | Marketplace KYB | Identity vendor connector + Tarka INFORM-shaped workflow | Default |
| Q5 | Live-commerce / counterfeit | Wave 3+; listing risk from evaluate metadata until brand connector | Default |
| Q6 | COD success | Both: fake-order at checkout, theft/POD at delivery | Default |
| Q7 | Chargeback consortium | Ethoca/Verifi-class early-alert connector yes; dispute PDF in Tarka | Default |

---

## Build vs connector matrix

| Capability | Strategy | Source |
|------------|----------|--------|
| Device integrity / emulator / spoof / place | **Connector** | Incognia, Fingerprint (existing plugins → production-ready); SHIELD optional SEA pack |
| Sanctions / PEP continuous | **Connector + OSS** | OpenSanctions/yente Match; Marble-like continuous ops (schedule, stamp, journal)—already partial |
| Identity KYB / worker face / RTW | **Connector** | Sumsub / Persona / Onfido / iProov-class (pick at connector config time) |
| Chargeback early alert | **Connector** | Ethoca / Verifi |
| Brand / counterfeit crawl | **Connector** (Wave 3+) | Commercial brand-protection API |
| Promo / referral typologies | **Build** (sibling) | `loyalty-abuse` → harden Tarka bridge + feed posture |
| Refund abuse scoring | **Build** (sibling) | `refund-abuse-risk` → Tarka bridge |
| Cancel / GPS offline leakage | **Build** (sibling) | `offline-cancel-risk` → Tarka bridge |
| Collusion / multi-sided graph packs | **Build** | Tarka graph + typology packs (OSS GNN *patterns*, not DIY device graph) |
| Local-rail playbooks (COD/PIX/UPI/M-Pesa social-eng) | **Build** packs | Typology + rule packs; payment-rail signals via connectors where needed |
| FTID / intake gate | **Build** (logic) + Downstream warehouse | Risk hold until intake hash/weight match; no DIY carrier network |
| Promote science / shadow CC | **Build** | Ojuri-shaped gates already in Tarka—finish label loop |
| Feature online serving honesty | **Build** contract | Feast *patterns*; keep feast_class_claim_allowed fail-closed until dual-diff proven |

---

## File / package map (intended)

| Unit | Responsibility |
|------|----------------|
| `services/decision-api/.../vendors/plugins/*` | Production connectors (device, KYC, chargeback, brand) |
| `services/decision-api/.../vertical_packs.py` + `rules/` | Vertical typology/rule packs per business type |
| `services/decision-api/.../*_bridge.py` | loyalty / refund / cancel / seller / promo bridges |
| `services/decision-api/.../typology*.py` | Typology control plane + breach ops |
| `services/graph-service/` | Cross-role relatedness + collusion cluster queries |
| `services/case-api/` | Dispute / KYB workflow cases / multi-party |
| `services/integration-ingress/` | Screening continuous ops + seller integrity ingress |
| `docs/compliance/*` | Honesty posture files / CLAIM_LOCK |
| Sibling repos | Source of scoring libraries; adapters under `adapters/tarka/` |

---

## Wave 0 — Foundations (all verticals)

Shared rails so vertical packs do not fork evaluate.

### Task 0.1: Connector contract standard

- [x] Document production connector contract: credentials, timeout, circuit, evidence tags, `ops_posture` JSON, fail-closed modes, contract tests (mirror Incognia/Fingerprint plugins).
- [x] Add posture fields: `live_claim_allowed`, `last_success_at`, `blockers[]` for each connector family.
- [x] Verify: unit tests for missing creds → unavailable (no silent fixture in prod path).
  - Shipped: `connector_contract.py`, `GET /v1/ops/connector-posture`

### Task 0.2: Vertical pack skeleton

- [x] Add pack IDs: `marketplace_goods` (alias), `food_delivery`, `last_mile` (alias), `e_hailing` in vertical packs.
- [x] Each pack declares: event checkpoints, required connectors, host-actions allowed.
- [x] Verify: `GET /v1/ops/vertical-pack-posture` lists packs with honesty notes.

### Task 0.3: Sibling bridge hardening

- [x] Production-ready bridges: `loyalty-abuse` (existing), `refund-abuse-risk`, `offline-cancel-risk` (URL, API key, circuit, evidence in audit).
- [x] Diligence/feed posture remains fail-closed until real feeds proven.
- [x] Verify: bridge down → evaluate continues with skipped_reason degradation (no silent success).

### Task 0.4: Answer detection questions Q1–Q7

- [x] Record answers in this plan (marketplace-first + defaults).

---

## Wave 1 — Food delivery / q-commerce (default first)

**Gaps closed:** promo farms, ATO redeem, refund abuse, ghost/cancel leakage, device LIVE path, friendly-fraud/POD features.

### Task 1.1: Promo & multi-account (build)

- [x] Food pack promo/collusion/cancel/refund/FTID rules + feature wiring (loyalty bridge already on redeem).
- [x] Entitlement: redeem checkpoint → loyalty bridge tags (existing); host honors friction tags.
- [ ] Verify: golden events for promo farm → throttle/block friction; honest user → allow (expand fixture suite).

### Task 1.2: Device connector production-ready (connector)

- [ ] Incognia + Fingerprint: complete LIVE readiness checklist, ops UI, contract tests with recorded fixtures + optional live smoke behind secret.
- [ ] Map vendor reason codes → food_delivery tags (emulator, clone, spoof, place mismatch).
- [ ] Verify: without creds `live_claim_allowed=false`; with creds smoke updates attempt log (no forge).

### Task 1.3: Refund abuse bridge (build)

- [x] Bridge `refund-abuse-risk` scores into evaluate / refund checkpoint; persist evidence on audit.
- [x] Honor Q3: default advisory; `action:refund_hold` when effect/score high.
- [x] Verify: map_refund_response + food `fd_refund_abuse_high` rule.

### Task 1.4: Cancel / offline-completion bridge (build)

- [x] Bridge `offline-cancel-risk` heads at cancel/reassign checkpoint.
- [ ] Graph writeback hints for device clusters from OCR device graph when present.
- [x] Verify: head→feature derive + food pack rules.

### Task 1.5: Dispute + AI refund-image posture (build + optional connector)

- [ ] Extend friendly-fraud / dispute path: POD hash mismatch, repeat refund rate, karma-style standing (from case history).
- [ ] Detection question follow-up: if AI-fake damage images are in-scope, add **vision vendor connector** (do not train DIY CV in Wave 1).
- [ ] Verify: dispute evidence pack includes new features.

---

## Wave 2 — E-hailing

**Gaps closed:** cross-role collusion pack, trip/location integrity via vendor + graph, account rental signals via face connector.

### Task 2.1: Cross-role collusion typology (build)

- [ ] Typologies: `self_ride_same_device`, `driver_rider_pair_velocity`, `fake_surge_demand_cluster`, `incentive_completion_spoof`.
- [ ] Graph queries: same device on driver+rider roles; repeated pair interactions; shared Wi-Fi/place (from Incognia place_id when LIVE).
- [ ] Enforcement per Q2 default.
- [ ] Verify: fixture graph with 1 device → 2 roles triggers pack; distinct honest devices do not.

### Task 2.2: Location integrity (connector-first)

- [ ] Prefer Incognia (or SHIELD) spoof/tamper/place signals over DIY GPS physics.
- [ ] Optional OSS-inspired haversine / route-consistency rules as *supplement* only (Tazama haversine pattern).
- [ ] Verify: spoof tag from vendor → evaluate tag + typology contribution.

### Task 2.3: Worker continuous auth connector (connector)

- [ ] Production connector: face match / liveness at shift-start + periodic re-auth; reason codes for account sharing.
- [ ] Case-api workflow: failed re-auth → suspend driving privilege host-action.
- [ ] Verify: missing connector → pack posture blocker `worker_auth_connector_unset` (fail-closed for e_hailing elevate).

### Task 2.4: Incentive abuse overlap with loyalty (build)

- [ ] Reuse loyalty multi_account / bot patterns for driver incentives; distinct event types `driver_bonus_claim`.
- [ ] Verify: multi-account driver bonus farm fixture.

---

## Wave 3 — Last-mile logistics

**Gaps closed:** COD fake orders, POD/FTID hold logic, cancel/theft (from Wave 1 OCR), mobile-money social-eng playbooks.

### Task 3.1: COD / checkout risk pack (build)

- [ ] Expand `offline_payment_features` into last_mile pack: COD velocity, address jigging, new-account COD high AOV, refusal rate.
- [ ] Q6: checkout scores fake-order risk; delivery scores theft/POD.
- [ ] Verify: COD abuse fixtures.

### Task 3.2: FTID / intake gate (build logic)

- [ ] Refund/return checkpoint: never auto-release high-risk refunds on carrier “delivered” alone; require intake receipt / weight / label match fields from Downstream.
- [ ] Connector optional: returns-platform webhooks (Loop-class) as event source—not DIY carrier network.
- [ ] Verify: FTID-shaped events (delivered scan, empty intake) → hold effect.

### Task 3.3: POD evidence (build + connector)

- [ ] Structured POD: photo hash, geofence, OTP; mismatch features into friendly-fraud path.
- [ ] Optional vision connector for POD photo tamper (same as Wave 1.5).
- [ ] Verify: geofence miss + OTP fail → review/deny delivery confirm.

### Task 3.4: Mobile-money / SMS social-eng playbook (build pack)

- [ ] Detection pack for off-platform payment requests (PIX/M-Pesa/UPI style): flags when payment instruction leaves in-app rail (metadata from host chat/payment events).
- [ ] Do not build SMS interception; host supplies signal that payment left official rail.
- [ ] Verify: off-rail payment request event → alert typology.

---

## Wave 4 — Goods marketplaces

**Gaps closed:** INFORM/DSA-shaped seller workflow, seller integrity, chargeback consortium, listing risk (limited), brand connector optional.

### Task 4.1: Seller KYB workflow (connector + build)

- [x] Identity vendor connector for doc/tax/bank verify (Q4) — `identity_kyb` plugin + env bootstrap.
- [x] Tarka workflow: high-volume seller thresholds → collect → verify → disclose → suspend (INFORM-shaped) — `marketplace_kyb` + `/v1/marketplace/kyb/*`.
- [x] Suspicious-activity report intake (INFORM consumer report → KYB) — `POST /v1/marketplace/kyb/suspicious-activity` (FinCEN SAR stays in case-api).
- [x] Verify: seller missing verify past SLA → `suspend_sales` host-action.

### Task 4.2: Seller integrity + payout hold (build)

- [x] Existing `seller_integrity_bridge` + `payout_hold_bridge` (prior P0/P1); marketplace pack tags drive holds.
- [x] Verify: low integrity / high payout velocity → payout hold tag (existing tests).

### Task 4.3: Chargeback consortium connector (connector)

- [x] Ethoca/Verifi-class early alert connector plugin (`chargeback_alert`) + pack rule + feature flag.
- [x] Webhook normalize → features + `dispute_hint` (`POST /v1/webhooks/chargeback-alert/{provider}`); auto-opens case-api dispute when `CASE_API_URL` + `tenant_id` (fail-soft).

### Task 4.4: Listing / counterfeit (connector, later)

- [x] Brand-protection family in connector posture + `mkt_listing_brand_hit` rule / feature.
- [x] Skip DIY crawl in-repo.
- [x] Brand vendor plugin HTTP (`brand_protection`) + env bootstrap.

---

## Wave 5 — Cross-cutting excellence

### Task 5.1: Typology control plane (OSS-shaped build)

- [ ] Deepen Tazama-shaped ops: pack → typology → channel aggregation telemetry; breach histograms already partial—add per-vertical dashboards.
- [ ] Optional Osprey/CEL export for typology starter packs.

### Task 5.2: Graph ring scoring (build, pattern from OSS)

- [ ] Production cluster APIs: device–account–role communities; relatedness evidence on evaluate.
- [ ] GNN optional behind stable “ring_score” interface; until LIVE labels exist, ship graph heuristics + vendor device edges (no fake GNN claims).

### Task 5.3: Promote science completion (build)

- [ ] Label feedback → McNemar/PSI/F1 loop already started; bind ACTIVE to labeled traffic only.
- [ ] Ojuri-shaped registry per vertical pack.

### Task 5.4: Continuous screening Motiva-class ops (connector + ops)

- [ ] Finish schedule + CronJob + stamp + journal; OpenSanctions/yente production connector path.
- [ ] Keep `motiva_claim_allowed=false` until continuous_ops_ready proven per tenant.

### Task 5.5: Feature serving honesty (build)

- [ ] Online feature contract dual-diff path; feast claim stays false until proven.

---

## Sequencing (default)

```text
Wave 0 foundations
    → Wave 1 food delivery  (promo + device LIVE + refund/cancel bridges)
    → Wave 2 e-hailing      (collusion + worker auth connector)
    → Wave 3 last-mile      (COD + FTID intake + POD + off-rail pay)
    → Wave 4 marketplace    (KYB workflow + chargeback consortium + brand)
    → Wave 5 cross-cut      (typology ops, ring score, promote, screening, features)
```

Parallelization: Wave 0.1–0.3 can run in parallel; Wave 1.2 (device connector) parallel with 1.1/1.3 once 0.1 done; Wave 4.3 chargeback connector independent after 0.1.

---

## Success criteria (per vertical)

| Vertical | Done when |
|----------|-----------|
| Food delivery | Promo farm + device LIVE smoke + refund_effect + cancel heads on evaluate/audit; diligence blockers explicit |
| E-hailing | Cross-role collusion pack live; worker auth connector posture; spoof tags from vendor |
| Last-mile | COD pack + FTID hold logic + POD mismatch features; off-rail payment typology |
| Marketplace | KYB state machine + identity connector + chargeback alert → dispute; seller suspend path |
| Global | No false LIVE/Motiva/Feast claims; connector posture machine-readable |

---

## Out of scope (explicit)

- Rebuilding Incognia/SHIELD/Fingerprint device graphs in-house
- DIY sanctions list maintenance (use OpenSanctions / commercial)
- DIY chargeback card-network consortium
- DIY brand web crawler
- Re-homing loyalty economics warehouse into Tarka
- Claiming peer parity with GrabDefence / Careem GNN / Marble Motiva without evidence

---

## References

- Market research canvas: `~/.cursor/projects/.../canvases/fraud-system-market-research-2026.canvas.tsx`
- Local codebase map: `.../fraud-requirements-codebase-map-2026.canvas.tsx`
- GitHub OSS approaches: `.../github-oss-fraud-approaches-2026.canvas.tsx`
- Sibling: `loyalty-abuse`, `refund-abuse-risk`, `offline-cancel-risk`
- OSS patterns: Marble, Tazama, Ojuri, Osprey, OpenSanctions/yente, Feast, DGFraud/AWS GNN blueprints
