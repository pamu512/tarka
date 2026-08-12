# B/C → A Uplift Plan (No LIVE Feeds)

> **PRIVATE / INTERNAL ONLY** — see [`docs/compliance/RATING_PRIVACY.md`](../../compliance/RATING_PRIVACY.md).  
> **For agentic workers:** Use superpowers:subagent-driven-development or executing-plans. Steps use checkbox syntax.

**Goal:** Move every B/C maturity dimension from the 2026-08-11 regrade to **A / A-** using fixtures, host-supplied signals, heuristic graph, and labeled synthetic holdouts — **zero LIVE vendor credentials required**.

**Architecture:** Keep connectors fail-closed (`live_claim_allowed=false` without creds). Raise grades by (1) deterministic feature→rule→typology packs, (2) in-process / Neo4j heuristic `ring_score` + cross-role queries on fixture graphs, (3) Downstream contract fields for FTID/POD, (4) Ojuri-shaped promote gates on **labeled fixture corpora** (not LIVE traffic), (5) golden vertical farm suites that prove honesty without partner pins.

**Tech Stack:** Existing decision-api, graph-service, case-api; JSON fixtures under `services/decision-api/tests/fixtures/verticals/`; no new vendor SDKs.

## Global Constraints

- No forged LIVE / Motiva / Feast claims; posture stays fail-closed.
- No re-home of loyalty multi-gate warehouse.
- A-grade = production-shaped software + fixture-proven behavior + honest ops surfaces — not tenant LIVE proof.
- Prefer host metadata + Downstream fields over DIY sensors/crawlers.

## What “A without LIVE” means

| Was | A bar (non-LIVE) |
|-----|------------------|
| Pack exists | Pack + golden farm fixtures + kill-gate + ops posture |
| Bridge wired | Bridge + recorded HTTP fixtures + degrade path tested |
| Feature flag | Feature derive + typology + host-action documented |
| Graph proxy | Heuristic `ring_score` API + cross-role fixture proof |
| Promote partial | Per-vertical labeled holdout + McNemar/PSI gate (fixture labels OK) |

---

## Track G — Graph / ring_score (C+ → A-)

**Files:**
- Create: `services/decision-api/src/decision_api/ring_score.py`
- Create: `services/decision-api/tests/test_ring_score.py`
- Create: `services/decision-api/tests/fixtures/verticals/e_hailing_collusion_graph.json`
- Modify: `services/graph-service/` community risk → expose cross-role device query (or decision-api pure heuristic on features)
- Modify: `services/decision-api/src/decision_api/evaluate/pipeline.py` — attach `ring_score` to audit
- Modify: `services/decision-api/src/decision_api/relatedness_evidence.py` — include ring block

**Interfaces:**
- Produces: `compute_ring_score(nodes, edges) -> {score_0_100, factors[], method: "heuristic_v1"}`
- Produces: `cross_role_same_device_from_graph(device_roles) -> bool`
- Honesty: `method` never `"gnn"` / `"live_vendor"` without evidence

- [x] **Step 1:** Failing test — fixture with 1 device on driver+rider → `cross_role_same_device=true`, ring_score ≥ threshold
- [x] **Step 2:** Implement pure heuristic (shared device, pair velocity, community_size lift from graph-service or in-memory edges)
- [x] **Step 3:** Evaluate audit includes `ring_score` + `relatedness_evidence.ring`
- [x] **Step 4:** Ops note: `gnn_claim_allowed=false`

**Verify:** fixture graph honest vs collusion; no vendor env needed.

---

## Track E — E-hailing depth (C+ → A-)

**Files:**
- Modify: `services/decision-api/src/decision_api/vertical_packs.py` (`e_hailing` typologies as rules already — add pair/surge rules)
- Create: `services/decision-api/rules/typology_e_hailing_v1.json` (or extend typology_definitions)
- Create: `services/decision-api/tests/fixtures/verticals/e_hailing_golden.jsonl`
- Create: `services/decision-api/tests/test_e_hailing_golden.py`
- Modify: `marketplace_features.py` — `driver_bonus_claim`, pair counts from metadata

- [x] **Step 1:** Golden suite: self_ride, pair_velocity, incentive_farm, worker_auth_failed (feature-injected, not LIVE face)
- [x] **Step 2:** Typology IDs mirror pack rules; typology-ops shows e_hailing drivers
- [x] **Step 3:** Host-action map documented: hard_challenge → suspend_driving after N repeats (deterministic counter in Redis/memory)
- [x] **Step 4:** `worker_auth` plugin remains connector; grade A on **fail-closed unset + feature injection path**

**Verify:** all golden cases pass without `TARKA_VENDOR_*`.

---

## Track L — Last-mile / FTID / POD (B- → A-)

**Files:**
- Create: `services/decision-api/src/decision_api/ftid_intake_gate.py`
- Create: `services/decision-api/tests/test_ftid_intake_gate.py`
- Modify: `offline_payment_features.py` / `marketplace_features.py` — refusal_rate, address_jig, pod_*
- Modify: `vertical_packs.py` — logistics + offline_payment rules for intake hold, POD OTP/geofence
- Create: fixtures `last_mile_ftid_golden.jsonl`

**Interfaces:**
- Produces: `evaluate_ftid_gate(delivered, intake_hash_ok, weight_ok, label_ok) -> {refund_hold, tags}`
- Contract: Downstream supplies booleans; Tarka never calls carriers

- [x] **Step 1:** Test — delivered=true, intake_hash_ok=false → `action:refund_hold` + `risk:ftid`
- [x] **Step 2:** POD features: `pod_geofence_miss`, `pod_otp_fail`, `pod_photo_hash_mismatch` → friendly-fraud tags
- [x] **Step 3:** COD refusal_rate / address hop rules (≥5 rules each pack if needed)
- [x] **Step 4:** Off-rail payment typology already flagged — add golden event

**Verify:** no Loop/carrier credentials; host fields only.

---

## Track P — Promote science / typology ops (B- → A-)

**Files:**
- Create: `services/decision-api/tests/fixtures/labels/vertical_holdouts/{marketplace,food_delivery,e_hailing}.jsonl`
- Modify: `backtest_promote_gate.py` / calibration promote — bind pack promote to labeled F1 + McNemar when labels present
- Modify: `typology_ops.py` — per-vertical breach histogram filter
- Create: `services/decision-api/src/decision_api/vertical_promote_registry.py`
- Modify: OpsShadow / ops endpoint to show per-pack promote posture

- [x] **Step 1:** Fixture labels (y=0/1) for each priority vertical (≥100 rows synthetic OK)
- [x] **Step 2:** Promote blocked when McNemar/F1 fail on holdout; allowed when pass
- [x] **Step 3:** `promote_live_claim_allowed` stays false; new field `promote_fixture_claim_allowed` for honesty
- [x] **Step 4:** Typology ops returns `by_vertical` block

**Verify:** promote science A-grade on fixtures; still honest about no LIVE labels.

---

## Track F — Food / sibling bridges polish (B/B+ → A-)

**Files:**
- Create: `tests/fixtures/verticals/food_promo_farm_golden.jsonl`
- Create: `tests/test_food_delivery_golden.py`
- Create: recorded HTTP fixtures for refund/cancel bridges (`respx`/`httpx` mock)
- Modify: pipeline — optional graph writeback hints from `partner_graph_hints` / device cluster features (no OCR LIVE)
- Modify: friendly_fraud_features — karma from case-api **fixture or optional URL** with mock

- [x] **Step 1:** Golden promo farm → loyalty tags / pack hits; honest micro-order → allow
- [x] **Step 2:** Refund/cancel bridge contract tests with recorded JSON bodies
- [x] **Step 3:** Device-cluster writeback from evaluate metadata `device_cluster_ids[]` (host-supplied)
- [x] **Step 4:** Case karma: `repeat_refund_rate_30d` from metadata or mock case-api

**Verify:** full food path green offline.

---

## Track C — Case karma / dispute join (B+ → A-)

**Files:**
- Create: `services/decision-api/src/decision_api/case_karma_features.py`
- Modify: evaluate enrichment — pull optional case stats; fail-soft
- Modify: chargeback webhook — attach dispute id into evaluate reprocess path (existing dispute_reprocess)
- Create: tests with mocked case-api JSON

- [x] **Step 1:** Features: `repeat_refund_rate_30d`, `dispute_loss_rate_30d`, `seller_case_count_90d`
- [x] **Step 2:** Marketplace/food rules fire on high karma risk
- [x] **Step 3:** CB alert → dispute → evidence PDF fields present in dispute_hint (no LIVE card network)

---

## Track B — Bridges / durability polish (B → A-)

**Files:**
- Modify: `marketplace_kyb_store.py` — optional SQLite/Postgres file backend for CI without Redis
- Modify: diligence / ops — single `GET /v1/ops/sibling-bridge-posture`
- Create: bridge posture aggregating loyalty/refund/cancel config + circuit

- [x] **Step 1:** Sibling bridge posture endpoint (configured / circuit / last_skip_reason)
- [x] **Step 2:** KYB store file backend for durable CI
- [x] **Step 3:** Document Downstream contracts in one guide (non-MkDocs-public if grades mentioned)

---

## Sequencing (all offline)

```text
G ring_score + cross-role fixtures
  → E e_hailing golden + typology
  → L FTID/POD/COD golden
  → P labeled promote + typology by_vertical
  → F food golden + bridge recordings
  → C case karma features
  → B bridge posture + KYB file backend
```

Parallel: G∥L∥P after ring_score interface frozen; F∥C after feature keys stable.

## Success criteria (A without LIVE)

| Dimension | Done when |
|-----------|-----------|
| Graph | Heuristic ring_score on evaluate + collusion fixture green; `gnn_claim_allowed=false` |
| E-hailing | ≥8 golden events; typology ops lists pack; repeat→suspend counter |
| Last-mile | FTID gate + POD OTP/geofence rules + COD golden |
| Promote | Per-vertical fixture holdout gates install/promote |
| Food | Promo/refund/cancel golden suite offline |
| Case karma | Features + rules from metadata/mock case-api |
| Bridges | Ops posture + recorded contract tests |
| Honesty | Still zero LIVE claims |

## Explicitly still not A (and OK)

- LIVE Fingerprint/Incognia smoke
- Real Ethoca/Verifi gateway
- Real face/RTW vendor
- Feast dual-diff / Motiva continuous with real lists

Those are **ops certification**, not software maturity for this uplift.

## Constraint update (2026-08-11) — no live tenants

There are **no live tenants and no external testers** available. Do not plan
work that requires paying customers, Ethoca onboarding, or device LIVE pins.
Do not block the roadmap waiting for one.

**Offline ceiling (critical bar):** strong **B** fixture-proven OSS decision OS.
Tenant-proven / LIVE **A** is unavailable by circumstance.

**What to build instead:** harder synthetic abuse corpora, adversarial near-miss
suites, party_graph fixture libraries, Downstream host-field contracts,
fail-closed connectors, `promote_fixture_claim_allowed` only, CI ECE gates.

**Honesty claim language:** “Fixture-proven multi-sided decision OS; connectors
ready; `live_claim_allowed=false`.” Never “production-proven on marketplace traffic.”
