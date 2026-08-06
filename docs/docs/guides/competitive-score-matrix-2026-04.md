# Competitive Score Matrix (0-5)

Scoring scale:

- `0`: Not present
- `1`: Concept only
- `2`: Early implementation
- `3`: Production-capable core
- `4`: Mature and operationally strong
- `5`: Category-leading

Competitor columns are **directional benchmarks** (product categories differ: device intel, location, platform risk, in-house velocity). They are **not** recomputed every release.

For a **finer-grained, module-by-module** rescoring after recent parity work — split by **OSS**, **full-stack paid**, **device enrichment**, and **location enrichment** — see **[competitive-module-rescore-post-parity-2026-04.md](./competitive-module-rescore-post-parity-2026-04.md)**.

---

## Git basis (for Tarka rows)

**Last doc refresh:** `cursor/competitive-scores-v12-v13-realign-7320` @ **`5d9f435`** (update this row when you realign scores or evidence). Older commit SHAs below are **historical anchors** unless you re-verify.

| Ref                         | Commit (short)           | Role                                                                                                                                                                                                                                                        |
| --------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Baseline matrix**         | Editorial **April 2026** | Original Tarka scores before train realignment.                                                                                                                                                                                                             |
| **`cursor/competitive-scores-v12-v13-realign-7320` (workspace)** | `5d9f435`                | **Doc sync pass:** optional GPS + IP-geo SDK paths, `location_context` + geo mismatch tags, graph **`Place` / `SEEN_AT`**, calibration ops endpoints, CI **48%** decision-api floor + **benchmark-latency-evaluate** + **secret-scan** workflows.          |
| `**master`** (this repo)    | `df3224c`                | *Historical snapshot* — counter manifest + replay, challenge policy templates, feature-service velocity wiring, vertical pack simulation benchmark, `inference_context` + ML factors path, OpenAPI for challenge policies.                                  |
| `**origin/release/v1.2.0`** | `a91b3e4`                | **3 commits ahead of historical `master` snapshot:** ingress `**GET /v1/integrations/scorecards`**, investigation-agent **production-hardening** (rate limits, workflows, case summary PDF, golden prompts), embedded collaboration chat (`chat_bridge`) workflow/attachments, docs “what’s new”. |
| `**origin/release/v1.1.0`** | `ddba68d`                | Older release branch; **same numeric matrix file** as baseline (scores were not versioned per branch historically).                                                                                                                                         |


**Merge-base (historical):** `master` and `origin/release/v1.2.0` shared `df3224c` at matrix authoring time; v1.2 adds integration reliability **scorecards** and **analyst/copilot** depth beyond that snapshot.

---

## Capability scores — Tarka by release train

Use these rows for **positioning and gap planning**. Competitors stay on the April 2026 benchmark row unless you rerun a formal competitive review.


| Capability                                    | Tarka baseline Apr 2026 | Tarka **v1.2** (realigned) | Tarka **v1.3** (projected) | Tarka **Wave6 honest** (2026-08-05) | Fingerprint | Incognia | Sift | Uber/Grab style benchmark |
| --------------------------------------------- | ----------------------- | -------------------------- | -------------------------- | ----------------------------------- | ----------- | -------- | ---- | ------------------------- |
| Inference normalization (cross-SDK + service) | 2.5                     | **3.0**                    | **3.25**                   | **4.2**                             | 4.5         | 4.0      | 4.0  | 4.5                       |
| Replay/tamper/MitM hardening                  | 2.5                     | **2.75**                   | **2.75**                   | **4.2**                             | 4.5         | 3.5      | 3.5  | 4.0                       |
| Counter/velocity platform maturity            | 2.0                     | **2.75**                   | **2.75**                   | **4.2**                             | 4.0         | 3.0      | 3.5  | 5.0                       |
| Location/co-location coherence                | 1.5                     | **2.0**                    | **2.25**                   | **4.2** (hybrid)                    | 3.5         | 5.0      | 3.0  | 4.0                       |
| Analyst decision acceleration                 | 2.0                     | **2.75**                   | **3.25**                   | **4.2**                             | 3.5         | 3.5      | 4.5  | 4.5                       |
| Rule/risk operations safety                   | 3.0                     | **3.5**                    | **4.0**                    | **4.2**                             | 4.0         | 3.5      | 4.0  | 4.5                       |


**Means (Tarka only, six capabilities):** baseline **2.25** · v1.2 **~2.79** · v1.3 **~3.04** · **Wave6 honest 4.2** (evidence: y_label healthy posture UI + join; HMAC signature CI gate + integrity tags; counter replay job + OpsCounters `last_parity_run`; partner fusion audit contract + fixture smoke; `/ops/qa` desk + QA APIs; file-backed rule telemetry + kill_criteria). Hybrid location/device = partner fusion quality, not native Incognia network — see [partner-enrichment-fusion.md](./partner-enrichment-fusion.md), [maturity-wave6-design](../../../superpowers/specs/2026-08-05-maturity-wave6-design.md).)

### Missed-mark bridge honesty (2026-08-05 Track D)

**Critical correction (same day):** Wave6/bridge blanket **4.2** walked back, then flag-fix + Engineering honesty stack. **Do not** re-advertise product-wide 4.2 or A++.

### Critical regrade — three buckets (2026-08-06, post S4/S5)

**Method:** Done well / Could-be-better / Missed the mark. Blindspots, logic fallacies, and bad assumptions marked **CRITICAL**. Aim bands are targets, **not** current scores. See [maturity-4-0-regrade.canvas.tsx](../../../superpowers/canvases/maturity-4-0-regrade.canvas.tsx) (synced IDE canvas: post S4 dual_diff `matched:true` + S5 install kill gate).

#### CRITICAL findings (C1–C7)

| ID | Type | Finding |
| --- | --- | --- |
| C1 | Fallacy | Related (graph) ⇒ loyalty abuse |
| C2 | Assumption | Signup/early location available to link accounts (false under privacy) |
| C3 | Blindspot | No order velocity · churn · LTV · loyalty÷LTV on clusters ([prerequisites](./loyalty-abuse-model-prerequisites.md)) |
| C4 | Fallacy | In-repo L1 / “floor ≥4.0” = product maturity |
| C5 | Fallacy | Four-week sim/playbook = L3 ops |
| C6 | Fallacy (mitigated) | Fixture ≠ live — enforced via `partner-fusion-proof.live.status` LIVE\|WAIVED (`REQUIRE_LIVE_PARTNER_PROOF=1`); location still not live-enriched |
| C7 | Blindspot | Equal-weight Location pillar for a loyalty-first thesis |

#### Six-cap (bucket-driven)

| Cap | Score | Bucket | Why |
| --- | ----- | ------ | --- |
| Inference | **3.4** | Missed | Plumbing ≠ loyalty economics (C3); live ECE unused |
| Replay/tamper | **4.0** | Done well | HMAC/integrity CI; not MitM product |
| Counters | **4.0** | Done well | S4: PR CI `dual_diff` Redis + `matched:true` required |
| Location (hybrid) | **2.5** | Missed | No live pin; wrong weight vs graph+economics (C2, C7) |
| Analyst | **4.2** | Done well | ops-qa Actions green |
| Rule/risk ops | **4.0** | Done well | S5: `/install` + promote share kill_criteria → 409 |

**Means:** six-cap ≈ **3.7** · overall ≈ **3.6** · Engineering **4.5** · Risk/Strategy **4.2** (strategy honesty stack; **4.5** = LIVE `.live.sha256`) · Fraud Ops **~3.8** (desk triad haircut: mocked webhook + no loyalty economics). Location remains **2.5**.

**Claim lock:** A++ / product-wide 4.2+ **CLOSED** while C1–C5/C7 bind the claim surface. Loyalty-abuse product claim also requires S9 upstream. Risk **4.5** and location ≥4.0 hybrid require replacing `WAIVED` with LIVE pin.

#### Bucket summary

| Bucket | Credit |
| --- | --- |
| **Done well** | Engineering honesty; Risk/Strategy LIVE\|WAIVED gate + promote CI + evidence index; Analyst ops-qa Actions; Replay CI; S4 matched:true CI; S5 install kill gate |
| **Could-be-better** | Fraud Ops live webhook; ECE on real labels; Risk 4.5 (live pin); Counters/Rule-risk stretch past 4.0 |
| **Missed the mark** | Loyalty-abuse effectiveness; location-as-linker; L2 *data* enrichment absent (process mitigated); product-wide 4.x claims |

> **Location = enrichment (product posture, 2026-08-06):** **Relatedness** is graph linkage (device / payment / referral / peers) plus **loyalty economics** gates — not signup GPS. The Location six-cap row is **hybrid enrichment** (partner Place/SEEN_AT, geo copresence, impossible travel) compared to Incognia; it is **not** the loyalty linker. Missed-mark **C2** (privacy-sparse location at signup) and **C7** (equal-weight Location pillar) are addressed in product posture by the [location enrichment reweight](../../../superpowers/specs/2026-08-06-location-enrichment-reweight-design.md) program — live Location ≥4.0 still gated by **S1** (partner pin).

---

## Why v1.2 numbers moved (evidence-linked)


| Dimension             | Delta vs baseline | Evidence in git / docs                                                                                                                                                                                                                     |
| --------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Inference**         | +0.5              | `inference_context` + ML top factors / summary in decision + Case Detail; golden/contract path; not yet full **calibration** (reliability diagrams still post–v1.2 per [release-gap-closure-schedule](./release-gap-closure-schedule.md)). |
| **Replay/tamper**     | +0.25             | Replay signatures + attestation path on trunk; challenge metadata + policies. **MitM / pinning matrix** still thin vs device vendors → cap below 3.0.                                                                                      |
| **Counters/velocity** | +0.75             | Counter **manifest v1**, token-gated **replay**, `fraud_aggregates` in feature-service + velocity query; [v1.2 tracker](../releases/v1.2.0-2026-05-30.md) still lists **partial** (key-prefix versioning, audit-export batch).             |
| **Location**          | +0.5 (v1.2 row) | **Trunk / RC:** optional GPS + IP-geo SDK hooks, `location_context` merge + **`sdk:geo_*`** mismatch tags, graph **`Place` / `SEEN_AT`**, calibration ops — still **not** Incognia-class device network; scores stay **directional**.                                                                                                                                                      |
| **Analyst**           | +0.75             | `**origin/release/v1.2.0` only:** copilot production config, workflows, case summary PDF, bridge hardening — faster **close-the-case** loop; still not Sift-class queue economics.                                                         |
| **Rule/risk ops**     | +0.5              | Challenge policy templates + `GET /v1/challenge-policies`; simulation vertical benchmark; ingress **scorecards** improve **connector** governance (related to rollout safety).                                                             |


**Ingress scorecards** (`a91b3e4`): `GET /v1/integrations/scorecards` — per-provider and overall scores from connectivity tests + config completeness. This supports **J1 integrate** and operational honesty; it does **not** by itself fix device or location signals.

---

## Why v1.3 numbers move (projected)

Source: [v1.3.0-2026-06-29.md](../releases/v1.3.0-2026-06-29.md) — Trust Center UI, **evidence export APIs**, release-governance **CI gates**, **signed artifacts**.


| Dimension                               | Delta vs v1.2 | Rationale                                                                                                                     |
| --------------------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **Inference**                           | +0.25         | Audit-facing **lineage** and exports improve **trust in scores**; still not a full calibration factory.                       |
| **Replay/tamper / Counters / Location** | —             | No committed step-change in those pillars in the v1.3 doc.                                                                    |
| **Analyst**                             | +0.5          | Evidence bundles and procurement-ready exports directly address **investigation and audit** narratives.                       |
| **Rule/risk ops**                       | +0.5          | Signed artifacts + governance checklist → **enterprise change control** closer to Uber/Grab internal bar, still OSS-operated. |


---

## Priority gaps (updated)

1. **Location/co-presence** improved on trunk (SDK + decision + graph) but remains the largest gap vs Incognia-class (benchmark 5.0) until trusted-device and co-presence depth match vendor bar — see **`release-gap-closure-schedule.md`** and **`v1.2.0-2026-05-30.md`** for remaining Day 60 items.
2. **Calibration pipeline** (reliability diagrams, drift monitors) — still post–v1.2 in [release-gap-closure-schedule](./release-gap-closure-schedule.md); caps inference below 3.5 until shipped.
3. **Counter platform** — finish parity items in [counter-replay-parity](./counter-replay-parity.md) before claiming **3.5+** on velocity.
4. Merge `**origin/release/v1.2.0` → `master`** or tag **v1.2.0** from that branch so marketing and scores refer to the same commit set.

---

## Historical table (April 2026 — single Tarka column)


| Capability                                    | Tarka | Fingerprint | Incognia | Sift | Uber/Grab style benchmark |
| --------------------------------------------- | ----- | ----------- | -------- | ---- | ------------------------- |
| Inference normalization (cross-SDK + service) | 2.5   | 4.5         | 4.0      | 4.0  | 4.5                       |
| Replay/tamper/MitM hardening                  | 2.5   | 4.5         | 3.5      | 3.5  | 4.0                       |
| Counter/velocity platform maturity            | 2.0   | 4.0         | 3.0      | 3.5  | 5.0                       |
| Location/co-location coherence                | 1.5   | 3.5         | 5.0      | 3.0  | 4.0                       |
| Analyst decision acceleration                 | 2.0   | 3.5         | 3.5      | 4.5  | 4.5                       |
| Rule/risk operations safety                   | 3.0   | 4.0         | 3.5      | 4.0  | 4.5                       |
