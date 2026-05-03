# Module-by-module competitive rescore (post–full-stack parity)

**Purpose:** Re-score each **Tarka product module** after recent parity work (calibration/drift surfaces, case desk aggregates + audit activity, ML lifecycle UI, counter catalog + replay helpers, inference explain panels, rule change log + policy-as-code CI, optional request signing, mobile attestation paths, compliance docs). Scores use the same **0–5** rubric as [competitive-score-matrix-2026-04.md](./competitive-score-matrix-2026-04.md).

**Git basis:** `ide/full-stack-parity-7320` @ **`e966c90`** (update when rescoring again).

**How to read competitor columns**

| Column family | Who it represents | What “good” looks like |
| ------------- | ----------------- | --------------------- |
| **OSS / composable** | Teams assembling **OPA**, **Feast**, **Kafka/Flink**, **Postgres/Redis**, **Grafana**, **Airflow**, small OSS fraud libs — no single vendor “brain” | You own glue code, observability, and incident response; fewer turnkey fraud primitives. |
| **Full-stack (paid)** | **Sift**, **Sardine**, **Forter**, **Riskified**, **SEON**, **Marble**-class — decision + case + rules + ML + integrations in one commercial product | Fast time-to-value, managed data networks, polished analyst UX, SLAs. |
| **Device enrichment** | **Fingerprint Pro**, **Castle**, **Darwinium**, **ThreatMetrix**-class APIs — browser/mobile session intelligence | High signal density, anti-tamper, global device graph, SOC2-ready ops. |
| **Location enrichment** | **Incognia**, **GeoComply**, **Precisely / MaxMind** enterprise geo, bank-grade geofencing | Co-presence, spoof resistance, regulated use-case depth. |

**Stance:** Tarka treats **enrichment vendors as complementary** — the gap is “how much you must still wire yourself” vs “how much ships in-box.”

---

## Scoring rubric (per sub-dimension)

| Score | Meaning |
| ----- | ------- |
| **0** | Absent |
| **1** | Docs / spike only |
| **2** | Works in demo; fragile ops |
| **3** | **Production-capable core** for teams that operate their own stack |
| **4** | Mature operations, strong defaults, few sharp edges |
| **5** | Category leader (usually multi-year R&D + data network effects) |

Sub-dimensions are scored **independently** then rolled into the **module mean** (simple average of listed sub-rows).

---

## 1. Decision engine & `inference_context` contract

**Scope:** `decision-api` evaluate path, schema/OpenAPI, `inference_context` normalization, ML factor merge, optional HMAC, challenge metadata.

| Sub-dimension | Tarka (post-parity) | OSS / composable | Full-stack paid | Device API vendors | Location API vendors |
| ------------- | -------------------: | ----------------: | ----------------: | -------------------: | --------------------: |
| Cross-surface schema consistency (web/mobile/server) | **3.4** | 2.0 (DIY per service) | **4.5** | 4.0 (vendor-owned shapes) | 3.5 |
| Explainability for analysts (structured drivers, tiers) | **3.5** | 2.5 | **4.2** | 3.8 | 3.0 |
| Calibration **truth** (reliability curves, held-out eval loops) | **2.4** | 2.0 | **4.0** | 3.5 | 3.5 |
| Calibration **ops** (snapshots, drift hint, CSV export, UI status) | **3.2** | 2.2 | 3.5 | 3.0 | 3.2 |
| Signed / authenticated ingress (HMAC, TLS story in docs) | **3.0** | 2.5 (varies by gateway) | **4.0** | 4.2 | 4.0 |
| **Module mean** | **3.1** | 2.2 | **4.0** | 3.7 | 3.4 |

**Largest gaps after build:** (1) **Calibration truth** vs paid + location vendors (they ship continuous eval as product). (2) **OSS** still wins on flexibility but loses on **unified contract** unless you invest heavily in glue.

---

## 2. Rules, simulation, shadow & policy-as-code

**Scope:** JSON rule packs, shadow mode, simulation/benchmark APIs, `validate_rule_packs.py` CI gate, rule change log + `X-Actor`, vertical packs.

| Sub-dimension | Tarka | OSS | Full-stack paid | Device | Location |
| ------------- | ----: | --: | ---------------: | -----: | -------: |
| Authoring ergonomics (safe iteration) | **3.2** | 2.8 (Git + OPA) | **4.5** (no-code + guardrails) | N/A | N/A |
| Shadow / champion–challenger | **3.4** | 2.0 | **4.2** | N/A | N/A |
| Simulation & vertical benchmark hooks | **3.3** | 2.2 | **4.0** | N/A | N/A |
| Governance (audit log, CI validation, approvals narrative) | **3.6** | 2.5 | **4.3** | N/A | N/A |
| Production telemetry on rule interactions (per-rule latency, conflict detection) | **2.5** | 2.0 | **4.2** | N/A | N/A |
| **Module mean** | **3.2** | 2.3 | **4.2** | — | — |

**Largest gap:** **Rule interaction telemetry** and **no-code guardrails** vs full-stack paid. OSS peers are **weaker than Tarka** on shadow + vertical benchmark wiring.

---

## 3. Counters, velocity & replay parity

**Scope:** Redis-backed counters, manifest + **merged catalog** API, Ops UI, replay scripts (`run_offline_parity`, aggregate diff tooling), `AGG_KEY_VERSION` story.

| Sub-dimension | Tarka | OSS | Full-stack paid | Device | Location |
| ------------- | ----: | --: | ---------------: | -----: | -------: |
| Declarative catalog & discoverability | **3.4** | 2.0 | **3.8** | 3.0 (session counts) | 3.2 |
| Online/offline replay **product** (one-click job, Airflow operator, UI diff) | **2.8** | 2.0 | **4.5** | 3.0 | 3.0 |
| Window library & self-serve new counters | **2.6** | 2.5 (Flink SQL) | **4.2** | N/A | N/A |
| Experiment tie-in (counter-level assignment + power analysis) | **2.2** | 2.0 | **4.0** | N/A | N/A |
| **Module mean** | **2.8** | 2.1 | **4.1** | 3.0 | 3.1 |

**Largest gap:** **Replay as a productized workflow** and **experimentation** vs Uber/Grab-style internal stacks and paid fraud platforms. Recent work **narrowed the catalog/visibility gap** more than the **scientific parity** gap.

---

## 4. Device & session intelligence (SDK + server fusion)

**Scope:** TS / Python / Kotlin / Swift SDKs, `device_context`, Play Integrity / App Attest wiring, VPN/emulator/root signals, server-side tag extraction, integrity confidence.

| Sub-dimension | Tarka | OSS | Full-stack paid | Device vendors | Location |
| ------------- | ----: | --: | ---------------: | -------------: | -------: |
| Signal breadth (web + mobile parity) | **3.5** | 2.5 | **4.2** | **4.8** | N/A |
| Anti-tamper / attestation depth | **3.2** | 2.0 | **4.0** | **4.7** | N/A |
| **Global** device reputation graph | **2.0** | 1.5 | **4.5** | **5.0** | N/A |
| Operational SDK rollout (crash analytics, kill switch, staged rollout) | **2.8** | 2.0 | **4.3** | **4.6** | N/A |
| **Module mean** | **2.9** | 2.0 | **4.3** | **4.8** | — |

**Largest gap (absolute):** **Global reputation network** vs device-enrichment vendors and paid stacks — **not closable** with OSS alone; requires either **partnership** or **tenant-owned** graph that matures over years.

---

## 5. Location & co-location coherence

**Scope:** `location_context`, IP/geo collectors, geo mismatch tags, graph `Place` / `SEEN_AT`, trusted zones, calibration hooks.

| Sub-dimension | Tarka | OSS | Full-stack paid | Device | Location vendors |
| ------------- | ----: | --: | ---------------: | -----: | ---------------: |
| IP / geo consistency checks | **3.0** | 2.5 | **3.8** | 3.2 | **4.5** |
| GPS / client telemetry path (optional) | **2.8** | 2.0 | 3.5 | 3.0 | **4.5** |
| **Co-presence** & behavioral geo (Incognia-class) | **2.0** | 1.5 | 3.8 | 3.5 | **5.0** |
| Spoof / mock / VPN-at-geo-layer fusion | **2.5** | 2.0 | **4.0** | 3.8 | **4.8** |
| **Module mean** | **2.6** | 2.0 | **3.8** | 3.4 | **4.7** |

**Largest gap (module vs module):** This module still has the **widest spread** vs **location enrichment leaders** (Δ ≈ **2.1** on module mean). Paid full-stack sits **~1.2** ahead — they bundle vendor APIs.

---

## 6. Graph service & link analytics

**Scope:** Neo4j-backed subgraph, communities, rings, risk propagation, entity tags, case-linked graph fetch.

| Sub-dimension | Tarka | OSS | Full-stack paid | Device | Location |
| ------------- | ----: | --: | ---------------: | -----: | -------: |
| Core graph queries & fraud patterns | **3.6** | 3.2 (pure Neo4j) | **3.8** | 3.0 | 3.0 |
| Graph **data quality** (identity resolution, dedupe) | **2.6** | 2.4 | **4.2** | 4.0 (cross-customer) | 3.5 |
| Analyst UX (saved queries, timelines, exports) | **2.8** | 2.5 | **4.0** | N/A | N/A |
| **Module mean** | **3.0** | 2.7 | **4.0** | 3.5 | 3.2 |

**Largest gap:** **Identity resolution + packaged analyst graph UX** vs paid. OSS **Neo4j-only** is comparable on raw query power, weaker on **fraud-specific UX**.

---

## 7. Case desk, SAR/disputes & analyst metrics

**Scope:** Case API, SLA, workflows, evidence bundle + decision audit join, SAR hooks, disputes, **full-tenant KPIs**, cohort compare, **desk-activity** from audit trail, WS feeds.

| Sub-dimension | Tarka | OSS | Full-stack paid | Device | Location |
| ------------- | ----: | --: | ---------------: | -----: | -------: |
| Case lifecycle + audit trail | **3.5** | 3.0 (e.g. ERP + Jira) | **4.3** | N/A | N/A |
| Queue economics (skills-based routing, SLA prediction) | **2.5** | 2.2 | **4.5** | N/A | N/A |
| Evidence / procurement bundles | **3.4** | 2.5 | **4.2** | N/A | N/A |
| Desk productivity metrics (what we added) | **3.2** | 2.8 | **4.0** | N/A | N/A |
| Dispute / chargeback ops depth | **2.8** | 2.5 | **4.2** | N/A | N/A |
| **Module mean** | **3.1** | 2.6 | **4.2** | — | — |

**Largest gap:** **Queue economics** and **dispute depth** vs Sift-class **operations research** in the product.

---

## 8. ML scoring & model lifecycle

**Scope:** `ml-scoring` ONNX registry, approve/activate/traffic/rollback/lineage, adaptive detector, optional SHAP/LGBM, **UI lifecycle page**.

| Sub-dimension | Tarka | OSS | Full-stack paid | Device | Location |
| ------------- | ----: | --: | ---------------: | -----: | -------: |
| Model registry & promotion workflow | **3.5** | 3.0 (MLflow + glue) | **4.2** | N/A | N/A |
| Monitoring & auto-rollbacks (data drift → action) | **2.5** | 2.8 (Evidently etc.) | **4.0** | N/A | N/A |
| Explainability at model boundary | **3.2** | 2.8 | **4.0** | 3.8 | N/A |
| **Module mean** | **3.1** | 2.9 | **4.1** | 3.8 | — |

**Largest gap:** **Closed-loop production monitoring** (drift → rollback → ticket) vs paid; OSS **can exceed** Tarka if you already run Evidently + MLflow heavily — Tarka is mid-pack here.

---

## 9. Integration ingress & “vendor mesh”

**Scope:** Integration ingress service, connectivity tests, **scorecards** API, webhooks, provider config.

| Sub-dimension | Tarka | OSS | Full-stack paid | Device | Location |
| ------------- | ----: | --: | ---------------: | -----: | -------: |
| Connector health & honesty (scorecards) | **3.4** | 2.8 | **4.0** | N/A | N/A |
| Pre-built connector **catalog** depth | **2.6** | 2.5 | **4.8** | N/A | N/A |
| Rate limiting, backoff, idempotency | **3.2** | 2.5 | **4.3** | N/A | N/A |
| **Module mean** | **3.1** | 2.6 | **4.4** | — | — |

**Largest gap:** **Pre-built integrations count** vs paid “platform of platforms.” Tarka is **stronger than typical OSS glue** on scorecards, still behind **Sardine/Sift** connector farms.

---

## 10. Investigation agent & collaboration

**Scope:** Investigation agent (chat, workflows, PDF exports), embedded collaboration chat (`chat_bridge`, Slack/Teams/Lark on **`/v1/chat/…`**), guardrails.

| Sub-dimension | Tarka | OSS | Full-stack paid | Device | Location |
| ------------- | ----: | --: | ---------------: | -----: | -------: |
| Workflow-aware copilot | **3.4** | 2.5 (generic LLM bots) | **3.8** | N/A | N/A |
| Enterprise chat governance (DLP, retention modes) | **2.8** | 2.0 | **4.2** | N/A | N/A |
| Evidence grounding & hallucination controls | **3.0** | 2.5 | **3.8** | N/A | N/A |
| **Module mean** | **3.1** | 2.3 | **3.9** | — | — |

**Largest gap:** **Enterprise compliance features** for chat (retention, DLP) vs paid; OSS alternatives are **weaker than Tarka** on fraud-specific workflow grounding if you compare to raw ChatGPT-in-Slack.

---

## 11. Analytics sink & reporting

**Scope:** Decision aggregates, hourly/top-entity APIs (as exposed to frontend), path to ClickHouse in architecture docs.

| Sub-dimension | Tarka | OSS | Full-stack paid | Device | Location |
| ------------- | ----: | --: | ---------------: | -----: | -------: |
| BI-ready exports & scheduled reports | **2.6** | 3.2 (Metabase/Superset) | **4.2** | N/A | N/A |
| Real-time dashboards for ops | **2.8** | 3.0 (Grafana) | **4.0** | N/A | N/A |
| **Module mean** | **2.7** | 3.1 | **4.1** | — | — |

**Largest gap:** OSS **general BI** beats Tarka on **charting breadth**; Tarka should **integrate**, not rebuild. vs paid, **curated fraud KPIs** still ahead of Tarka’s **generic** analytics layer.

---

## 12. Platform security, CI & compliance narrative

**Scope:** GitHub Actions (Ruff, tests, benchmarks, secret scan, rule pack validation), compliance guides, regulated markets pack, request signing.

| Sub-dimension | Tarka | OSS | Full-stack paid | Device | Location |
| ------------- | ----: | --: | ---------------: | -----: | -------: |
| Supply chain & CI hygiene | **3.6** | 3.0 (varies) | 3.5 (opaque) | 4.0 | 4.0 |
| Certifications (SOC2 type II, ISO) as **vendor** | **1.5** (OSS repo; customer attests) | 1.5 | **5.0** | **4.8** | **4.5** |
| Auditability of **customer** controls | **3.5** | 3.0 | 3.8 | 3.5 | 3.5 |
| **Module mean** | **2.9** | 2.5 | **4.1** | 4.1 | 4.0 |

**Largest gap:** **Formal third-party certifications** — structural for paid vendors; Tarka’s strength is **customer-owned evidence** (audit trails, bundles), not a badge.

---

## Summary: where is the gap largest **now**?

Sorted by **worst Δ vs best-in-class column** for that module (approximate).

| Rank | Module | Tarka mean (this pass) | Toughest benchmark column | Δ (approx) | Notes |
| ---- | ------ | ----------------------: | --------------------------- | ---------: | ----- |
| **1** | **Location & co-location** | **2.6** | Location vendors (**4.7**) | **~2.1** | Still the **dominant** structural gap; APIs + physics of spoof resistance. |
| **2** | **Device intelligence** | **2.9** | Device vendors (**4.8**) | **~1.9** | Network reputation & anti-tamper operations, not feature checkboxes. |
| **3** | **Counters / replay** | **2.8** | Full-stack paid (**4.1**) | **~1.3** | Catalog/UI improved; **experiment + one-click replay product** did not. |
| **4** | **Analytics / BI** | **2.7** | Full-stack paid (**4.1**) | **~1.4** | Consider **embrace Grafana/Metabase** as first-class export targets. |
| **5** | **Decision / calibration truth** | **3.1** (module) | Paid / loc. on **calibration truth** sub-row (**~4.0**) | **~0.9–1.6** on weakest sub-rows | Ops calibration improved; **science** still behind. |
| **6** | **Integration catalog** | **3.1** | Full-stack paid (**4.4** on mesh) | **~1.3** | Scorecards help honesty; **connector count** does not. |

**Relative bright spots (Tarka closest or ahead of some columns):**

- **Rules / shadow / policy-as-code** vs **OSS** (Tarka **~3.2** vs OSS **~2.3**).
- **Graph primitives** vs **OSS Neo4j-only** (similar core; Tarka packages fraud patterns).
- **CI / openness** vs **opaque paid** (different game: transparency vs badge).

---

## Aggregate means (for executive comparison)

Weighted equally across the **twelve** modules above (each module mean vs column mean of modules where that column applies).

| Benchmark column | Approx mean score |
| ---------------- | ----------------: |
| **Tarka (post-parity)** | **3.0** |
| **OSS / composable** | **2.5** |
| **Full-stack paid** | **4.1** |
| **Device enrichment** | **3.6** (across applicable modules) |
| **Location enrichment** | **3.5** (across applicable modules) |

**Interpretation:** Tarka sits at the **production-capable OSS control plane** tier (**~3.0**), **ahead of raw OSS glue** on fraud-specific modules, still **~1.1 points** behind **full-stack paid** on average — concentrated in **location**, **device reputation**, **connector depth**, and **calibration science**.

---

## Related docs

- [competitive-score-matrix-2026-04.md](./competitive-score-matrix-2026-04.md) — historical train + benchmark row.  
- [competitive-critical-review-2026-04.md](./competitive-critical-review-2026-04.md) — narrative critique.  
- [tarka-gap-code-map.md](./tarka-gap-code-map.md) — gap → code pointers.  
- [sdk-scorecard-2026-01.md](./sdk-scorecard-2026-01.md) — SDK-only calibrated view.
