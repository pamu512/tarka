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
| `**origin/release/v1.2.0`** | `a91b3e4`                | **3 commits ahead of historical `master` snapshot:** ingress `**GET /v1/integrations/scorecards`**, investigation-agent **production-hardening** (rate limits, workflows, case summary PDF, golden prompts), collaboration-chat-bridge workflow/attachments, docs “what’s new”. |
| `**origin/release/v1.1.0`** | `ddba68d`                | Older release branch; **same numeric matrix file** as baseline (scores were not versioned per branch historically).                                                                                                                                         |


**Merge-base (historical):** `master` and `origin/release/v1.2.0` shared `df3224c` at matrix authoring time; v1.2 adds integration reliability **scorecards** and **analyst/copilot** depth beyond that snapshot.

---

## Capability scores — Tarka by release train

Use these rows for **positioning and gap planning**. Competitors stay on the April 2026 benchmark row unless you rerun a formal competitive review.


| Capability                                    | Tarka baseline Apr 2026 | Tarka **v1.2** (realigned) | Tarka **v1.3** (projected) | Fingerprint | Incognia | Sift | Uber/Grab style benchmark |
| --------------------------------------------- | ----------------------- | -------------------------- | -------------------------- | ----------- | -------- | ---- | ------------------------- |
| Inference normalization (cross-SDK + service) | 2.5                     | **3.0**                    | **3.25**                   | 4.5         | 4.0      | 4.0  | 4.5                       |
| Replay/tamper/MitM hardening                  | 2.5                     | **2.75**                   | **2.75**                   | 4.5         | 3.5      | 3.5  | 4.0                       |
| Counter/velocity platform maturity            | 2.0                     | **2.75**                   | **2.75**                   | 4.0         | 3.0      | 3.5  | 5.0                       |
| Location/co-location coherence                | 1.5                     | **2.0**                    | **2.25**                   | 3.5         | 5.0      | 3.0  | 4.0                       |
| Analyst decision acceleration                 | 2.0                     | **2.75**                   | **3.25**                   | 3.5         | 3.5      | 4.5  | 4.5                       |
| Rule/risk operations safety                   | 3.0                     | **3.5**                    | **4.0**                    | 4.0         | 3.5      | 4.0  | 4.5                       |


**Means (Tarka only, six capabilities):** baseline **2.25** · v1.2 **~2.79** (after location bump) · v1.3 **~3.04** (location **2.25** vs **2.0** on v1.2; other rows unchanged from matrix above).

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
