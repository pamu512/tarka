# Buyer pilot assessment — claims vs proof

**Tip:** `a0a35918c88aed52456fffac969021c953948735` (`origin/master`, 2026-09-08). Merge of G9 soak-checklist PR #414.

**What this is:** diligence memo for a **paid VPC / self-host pilot**. Not a brochure. Not a GitLab-grade install claim. Not traction.

**What this is not:** users, LOI volume, ARR, named live tenants, or a SOC 2 / PCI cert. Those are **MUST-NOT**.

**UI F1–F3** (receipt-why 403 / leftover Create draft without why / silent Observe Promote) are **open on this tip**. A separate agent owns the fix. This memo treats them as **pilot blockers** for RiskOps/frontline — not for an eng-led parallel plane.

**North star:** Does Tarka make the cut vs this buyer’s BAU? If yes, which modules, and how without touching BAU? Not a feature tour.

---

## 0. CUT / MODULES / BAU / FAIL

Buyer stack (keep; do not invent extras): Drools + Groovy · Hive supervised scores (FI **mid-60s**, a few **high ~80**) · shared MLOps **Bedrock** · Excel/Jupyter · Tableau (BI-owned) · S3/BQ/Azure/GCP · skip-only Janus · ~**7% GMV** detected loss · ~1.9B orders/year (buyer-given; not tip-proved).

Allowed improvement axes vs BAU: **reduced opex**, **reduced engineering resources**, **shorter SLAs**, **faster pack/iterate**, **clearer receipt-why / override feedback**. **MUST-NOT:** higher FI · detect more than ~7% GMV.

### CUT — does Tarka even make the cut?

**Conditional PASS** — only on tip-proved iterate / why, not on FI or GMV.

| Axis | Tip can promise? | Evidence |
|------|------------------|----------|
| Faster pack / iterate | **Yes (eng-led)** — 1–N JSON Observe packs → human Promote, no Drools rewrite, no Hive/MLOps touch | Rust evaluate + `rule_api` Promote; `emit_only` dual-run |
| Clearer receipt-why / override | **Yes on API** — pack-why + override why + late-label bind on `evaluation_token` | `evaluate.py` / receipts; `POST /v1/overrides`; late-label webhook |
| Reduced opex / eng FTE / shorter SLA | **Not as a number** — no tip measurement. Do not invent $ / FTE / minutes | Plane exists; **MUST-NOT** quote opex/SLA |
| Higher FI (mid-60s → 80) | **FAIL** | Wrong plane. Hive / Bedrock / shared MLOps |
| Detect more than ~7% GMV | **FAIL** | 7% is their current coverage, not a Tarka target |

**FAIL Tarka** if Drools+Groovy + Hive models + Tableau BI + skip-Janus is **already stable** and they do not need a faster iterate / receipt-why plane. **FAIL** if the only ask is FI or GMV. **FAIL** a RiskOps-led desk cut until F1–F3 (receipt-why 403, leftover draft without why, silent Promote).

### MODULES — full stack vs few modules?

**Few modules. Not full stack.**

| In the day-1 cut (beside Drools) | OUT unless the buyer asks later |
|----------------------------------|----------------------------------|
| Rust evaluate | Graph / hop (buyer Janus is **non-queryable** / skip-only) |
| JSON packs, Observe → human Promote | Hunt |
| Receipts + override why + late-label join | Advise / native Bedrock (`SHADOW_LLM_BACKEND=bedrock` **refuses**) |
| Hive scores as **payload enrichment** only | Residual case CRM; Tableau replacement |

Beachhead packs (Observe first): promo / refund / payout / COD / false declines. Chargeback = late label, not the SKU.

### BAU — how without affecting current operations?

Parallel plane only. No Drools cutover in the pilot window.

| BAU stays | Tarka does |
|-----------|------------|
| Drools + Groovy **live** | Shadow / Observe packs; `enforcement.mode = emit_only` |
| Hive microservices + scores | Sit-beside on the **inbound payload** (not `VENDOR_SCORE_URL` as decide-time Hive) |
| Tableau / BI owns KPIs | Export / webhook feed only |
| Skip-only Janus | `GRAPH_SERVICE_URL` **empty** (hops off) |
| Shared MLOps Bedrock | No token sale; no model rewrite |

GitOps JSON packs + VPC clone (`make doctor && make demo` or product compose). No forced rewrite of risk Hive microservices. No Drools/Groovy importer.

**If strategy / frontline would touch leftover or Promote loops:** F1–F3 are **open** — keep those humans on BAU until a separate UI agent lands. Eng-led API dual-run does not need the desk.

### FAIL — when not to switch

- BAU already stable and Tarka cannot promise a concrete iterate / why improvement on tip.
- Ask is “get FI to 80” or “detect more than ~7% GMV.”
- Full-stack / rip-replace Drools + Hive + Janus + Tableau.
- Desk-led leftover / Promote as week-1 (F1–F3).

**Locked call:** CUT = conditional PASS on faster pack/iterate + API receipt-why. MODULES = evaluate + packs + receipts + override why. BAU = emit-only beside Drools. Else FAIL.

---

## 0a. Switch economics (given metrics only)

Buyer-given — do not invent others. This is the switch question, not a feature tour.

| Metric | Given | What a switch would have to buy |
|--------|-------|----------------------------------|
| Supervised FI | most models **mid-60s**; a few **high ~80** | Tarka is **not** that plane. **MUST-NOT** “move FI to 80.” If Hive FI is the bottleneck, **do not switch**. |
| Loss detected rate | **~7% of GMV** (detected loss / GMV) | Their current **coverage** of loss they already catch. **MUST-NOT** “detect more GMV” or treat 7% as a Tarka target. |

**Does it make sense to switch to Tarka?**

| If the bottleneck is… | Switch? |
|-----------------------|---------|
| Hive supervised-model FI (mid-60s) | **No.** Tarka does not train those models and does not claim to move FI to 80. |
| Operating / iterating already-detected loss beside Drools + Hive scores (packs, receipts, override why, late-label, Observe→Promote) | **Conditional yes** — parallel evaluate plane only. **Not** rip-replace. **Not** “detect more GMV.” **Not** an FI promise. |
| Frontline / strategy *desk* loop on that ~7% | **Not yet.** Tip helps *work that loss* only if desk loops work. **F1** (receipt-why 403 / PackWhyStrip), **F2** (leftover Create draft without why), **F3** (silent Observe Promote) are **open** — blockers for RiskOps/frontline use of the loop. Eng-led API dual-run (`emit_only`) is still the honest path. |

**Locked call:** operate the ~7% detected-loss loop cheaper/faster (opex / eng / SLA **axes** — not measured $). **MUST-NOT** move FI mid-60s → 80. See §0 CUT / FAIL.

---

## 1. Buyer frame

Shape only. No company name.

| Fact the buyer brings | What the 2–4 week pilot is trying to prove |
|-----------------------|--------------------------------------------|
| Multi-modal marketplace: ~20 countries, ~400 cities, on the order of **1.9B orders/year** | Evaluate + JSON packs + receipts run on **their** VPC. Tip does **not** claim 1.9B. Laptop / founder-ops figures are not product traction. |
| Lean shared engineering — not a greenfield platform team | A small eng slice can land `make doctor && make demo` (or product compose) **without** owning MLOps. |
| LLM already in BI (Gemini and/or Microsoft Copilot). **Shared MLOps owns AWS Bedrock** (+ broader AWS). Risk owns **supervised scoring microservices**; outputs land in **Hive**. | Tarka is evaluate / packs / receipts. Advise is BYO or **off**. Tarka does **not** replace Hive models, Bedrock training, or those microservices. No Tarka-sold tokens. |
| Ops analysis: **Excel + Jupyter**. Leadership KPIs: **Tableau, owned by BI** — not the risk desk. | Tarka must not assume a pack-authoring desk culture or that RiskOps owns reporting. Desk does **not** replace Tableau. |
| Data plane is messy multi-cloud: **S3, BigQuery, Azure, GCP** | First-party evaluate works **without** one warehouse. Tarka SoR for decisions is buyer **Postgres + Redis**, not their lake. |
| **Frontline** handles residual review. **Strategy is siloed** (promo / refund / payout / device / …). | Pack-why on leftovers without strategy background. Siloed authors can ship JSON **without** waiting on shared MLOps — and without a husk builder. |
| Graph today: **JanusGraph**, severely limited — nodes largely **non-queryable**; engine can only return **skip** from **configured node relations** (not rich hop/pack evaluate on arbitrary reads). | Do not treat that as a rich queryable identity graph. Tarka empty `GRAPH_SERVICE_URL` = hops off. Wiring AGE / Hunt / named hops is a **second workstream**, not a free Janus upgrade. |
| Rule base today: **Drools + Groovy** (not Tarka JSON packs). | No drop-in Drools import on tip. Tarka is a **parallel evaluate plane** or phased cutover. Drools may stay residual during the pilot. |
| Supervised FI: most models **~mid-60s**; a few **~high 80**. Detected loss **~7% of GMV** (buyer-given; not a Tarka KPI). | Tarka does **not** raise Hive FI. Tip helps **operate/iterate** already-detected loss — not claim a higher GMV %. |

**Org boundaries (do not smash):**

| Owner | Owns | Does not own |
|-------|------|----------------|
| Shared MLOps | Bedrock / AWS training loops | Tarka evaluate; live pack Promote |
| Risk (supervised services) | Existing model microservices + Hive scores | Tarka desk; Tableau |
| BI | Tableau / leadership KPIs | Tarka leftover queue |
| Strategy (siloed) | Policy intent in Excel / notebooks + Drools / Groovy authors | Production model training; Tarka JSON as a second language |
| Frontline | Residual review | Pack authoring; reporting SoR |
| Tarka (this product) | Evaluate + JSON packs + receipts + Observe canary | Hive warehouse; Tableau; Bedrock; their microservices; buyer Janus skip-graph |

**Pilot success (2–4 weeks), if it is a go:**

1. Evaluate plane on their infra (compose first; Helm `prod-on-k8s` is core-api HA — **desk OFF**).
2. **1–N JSON Observe packs beside Drools** (not a Drools rewrite). Receipts from Tarka evaluate.
3. Observe canary → **human** Promote (model never evaluates or Promotes).
4. Empty plane URL = that plane off.
5. `enforcement.mode = emit_only` unless they later contract handoff.
6. Eng hands BI **export/join contracts** — Tarka desk does not become Tableau.
7. Phase 1 graph **off** (or skip-relations as payload enrichment only). Named-hop / Hunt is phase 2.

**Pilot non-goals:** GitLab-grade install (G9 unsigned). Primary decisioner. Banks. Consortium. Hosted Tarka Cloud. 1.9B soak. Migrating Hive/Bedrock training onto Tarka. Replacing Tableau. Treating skip-only Janus as Tarka hops. Replacing the Drools/Groovy estate in 2 weeks.

---

## 2. Buyer questions (this shape)

### Q1 — Can a small eng slice land evaluate + packs + receipts without owning MLOps?

**Yes, for clone / compose.** Rust JSON packs decide. Shared MLOps is not on the Day-1 path.

| Proof | Gap |
|-------|-----|
| `make doctor && make demo` → lite + fraud-desk + `walk_receipts.py`. | CI runs **mocked** doctor + walk only. No job runs full `make demo`. |
| Evaluate is Rust (`crates/tarka-core`, `tarka_rule_engine`). | Host Postgres/Redis on `5432`/`6379` **fails doctor**. |
| `GRAPH_GNN_BETA_URL` unset in compose. Ring / graph-risk is a challenger. | Turning GNN/L2 on later **would** touch shared MLOps. Do not do that in week 1. |

**Helm honesty:** `prod-on-k8s` is evaluate HA (external PG/Redis, frontend **OFF**, Shadow **OFF**). Frontline/strategy desk is `make product` or `enterprise-desk-on-k8s` — still beta, **not** the grade.

### Q2 — Can siloed strategy author / Promote without a husk builder, without MLOps, from Excel / Jupyter?

**Author JSON: possible after a translator step. There is no Excel / notebook → pack path. Promote to live: not desk-safe.**

| Proof | Gap |
|-------|-----|
| JSON packs are the SoT ([`rules.md`](../docs/guides/rules.md)). Visual builder is a **product-skin** job — not required. | Tarka does **not** assume a pack-authoring desk culture. No `.xlsx` / `.ipynb` importer. Credit-card example: “export features in your notebook and POST evaluate” — scoring, not pack compile. |
| Event types include `promo`, `cod`, `payout`, `order`, `delivery`, `refund`. Field registry maps buyer keys → pack fields (product Postgres overlay). | Siloed teams share **one** Observe desk. No per-department namespace. Demo PUT maps **403**. |
| Human Promote gated on `POST …/shadow-packs/{id}/promote`. Auto-promote default **off**. | **F3 OPEN:** `/ops/shadow` Promote has **no confirm**. Lean `/observe` “Promote to Active” **bypasses** leftover/science gates. |

A husk builder is **not** the blocker. **Excel/Jupyter are not Tarka author surfaces.** Eng (or a trained analyst) must write JSON. **Silent Promote is.**

### Q3 — Can frontline see pack-why on leftovers without strategy background?

**Not reliably. Frontline blocker.**

| What exists | What frontline hits |
|-------------|---------------------|
| Leftover row: `pack_id` + `rule_hits` text + receipt link. | Pack id is **not** a `/rules` link. Hunt leftover pack props are **unused**. |
| `PackWhyStrip` never hides, never invents. | `/decisions/:traceId` uses **analyst** audit. Missing role → **403**. Strip starved. **F1 OPEN.** |
| Workbench / Hunt fall back to `minimal`. | Receipt click from leftovers does **not**. |
| REVIEW / DENY mint leftovers. | Empty graph URL **hides** `/leftovers`. |

**F2 OPEN:** Create draft sends `skip_reason: "desk skip"`.

### Q4 — BYO LLM (BI Gemini / Copilot) and Bedrock (shared MLOps)?

**Empty URL = off (honest). Gemini API: factory-proved, not Day-1. Microsoft Copilot: no plane. Bedrock: OpenAI-compat proxy only — no native SDK. Not Vertex-only. Not Tarka-hosted.**

| Buyer assumption | Tip fact | Status |
|------------------|----------|--------|
| No Tarka tokens / branded model | `make demo` never starts `shadow_agent`. Helm Shadow **OFF**. | **PROVED** / **MUST-NOT** sell tokens |
| Microsoft Copilot / BI chat authors packs | No connector. `COPILOT_*` is investigation-agent assurance. | **MUST-NOT-CLAIM** |
| Gemini already in BI | `SHADOW_LLM_BACKEND=gemini` + `GEMINI_API_KEY` → Google OpenAI-compat URL. New wire, not a BI embed. | **PROVED after config** (unit). Not Day-1. |
| Shared MLOps Bedrock | Factory comment: **no** `azure` / `vertex` / `bedrock` backend name (`llm_client.py`). `SHADOW_LLM_BACKEND=bedrock` **refuses**. Use `self-hosted` + OpenAI-compat URL (Bedrock proxy if they have one). VISION / older INDEX listed Bedrock as first-class — **over-broad**. INDEX Advise line tightened this PR. | **PARTIAL** |
| Closed omniscient author loop | Scout may draft Observe. Humans Promote. | **MUST-NOT** as shipped |

Shared MLOps keeps Bedrock. Risk does not need MLOps to evaluate. Advise is optional later.

### Q5 — Multi-party / multi-modal (diner + driver + vendor)?

**PARTIAL.** `parties[]` persist on the receipt. Empty graph invents no edges. Not a live three-sided SKU.

Allowlist `entity_type`: `user, device, ip, phone, payment, place, promo, order` — **not** diner / driver / vendor. Unsigned types **422**. Fixture tenant `mkt-demo-2026` ≠ live marketplace. Hop packs stay `mode=shadow`.

### Q6 — Scale (1.9B)?

**MUST-NOT claim 1.9B — or any production TPS — from tip.** README: local figures only. `hey` / `k6` deferred. G9 TPS row blank.

Pilot must prove: named cluster + digest pin + **buyer event shape** + measured p95/5xx at **their** TPS. Founder-ops ≠ traction. No invented users / LOI / ARR.

### Q7 — Data plane: evaluate without one warehouse? Tarka SoR vs S3 / BQ / Azure / GCP?

**Evaluate does not require their lake. Tarka’s decision SoR is Postgres + Redis (AGE if Hunt is on). That is a new store — not a Hive / BQ / S3 replacement.**

| Claim | Tip honesty |
|-------|-------------|
| Ingest / evaluate on first-party events without one warehouse | **PROVED.** `POST /decisions/v1/decisions/evaluate` or event-ingest → NATS. No BQ/S3/Azure required. |
| Late-label / label fabric vs warehouse-grade reality | **PARTIAL.** Bind is `POST /v1/webhooks/late-label` onto the **Tarka receipt** (`evaluation_token`). Export `GET /v1/exports/receipts` (`tarka.receipt_label_export/v1`) — buyer **loads the lake**. Tarka does **not** host Snowflake/BigQuery (`warehouse-sink-v1.md`). No Hive / BQ connector. Analyst role required on export. |
| Single SoR | **MUST-NOT** claim Tarka unifies S3+BQ+Azure+GCP. SUPPORT: buyer owns warehouse / queue. |

**Thin seams (what Tarka actually wants locally vs their estate):**

| Tarka plane | Tip default | Buyer estate | Honesty |
|-------------|-------------|--------------|---------|
| Decisions / audit / packs / labels | **Postgres** (external on `prod-on-k8s`) | Not BQ / Hive | New SoR. G6 backup is PG drill, not lake snapshot. |
| Velocity / OIDC state / ingest idempotency | **Redis** (ephemeral) | — | Empty Redis after restore is expected. |
| Hunt / hops | **AGE** on same PG, or `GRAPH_SERVICE_URL` | — | Empty URL = hops off. AGE restore is **volume**, not `pg_dump`. |
| Analytics OLAP | Optional **ClickHouse** | They have BQ / Hive / Tableau | ClickHouse is **not** evaluate SoR. Do not require it for the pilot. |
| Object / PIT ML export | Optional S3 prefix / local parquet | They have S3 | `POST /v1/ml/export/pit-parquet` + `cold_tier_evidence_to_s3.py` — opt-in, not Day-1. Weekly scorecard script is a **stub**. |
| Lake | Buyer-owned | S3 / BQ / Azure / GCP | JSON export + example SQL. Empty sink = local only. |

### Q8 — Tableau (BI-owned) vs Tarka “dashboards”?

**Tarka must not assume RiskOps owns reporting. Desk bake-off is not Tableau. Do not replace Tableau.**

| Surface | What it is | BI-wireable? |
|---------|------------|--------------|
| `GET /v1/observe/loop-metrics` (alias `/v1/ops/bakeoff`) | Observe loop JSON (`tarka.loop_metrics/v1`). `evaluate_count` / `rule_hit_rate` still **null** (forward). Empty tenant → zeros / nulls. | **Yes** — HTTP JSON. Thresholds are **tenant policy**, not Tarka morals. |
| `LoopScoreboard` on `/ops/shadow` | Desk chrome over the same JSON. | **No** — not a BI extract. |
| `GET /v1/exports/receipts` | Receipts + labels + `training_rows`. Join = `evaluation_token`. | **Yes** — this is what eng should hand BI. Role `analyst`. |
| `decision.emitted` webhook | Every evaluate (emit-only). | **Yes** — stream into their bus → Tableau extracts. Empty URL = off. |
| Late-label webhook **inbound** | BI/finance/Hive jobs **push** labels in. | **Yes** — they already own late outcomes. |
| `GET /v1/analytics/scorecard` + `export_weekly_scorecard_json.py` | Decision mix / rule hits. Script README: **N4.2 stub**. | **PARTIAL / theater** as a weekly KPI product. |
| Frontend `/analytics` | Product-skin desk. | **MUST-NOT** as leadership SoR. |
| Grafana SLO burn | Operator / SRE, not Risk KPI. | Separate from Tableau. |
| `service-slos-v1` nines | Aspirational / buyer-owned. | **MUST-NOT** as a Tarka SLA. |

**What eng must hand BI (pilot):**

1. `tarka.receipt_label_export/v1` schema + `evaluation_token` join (`warehouse-sink-v1`, `label-join-v1`).
2. Optional `decision.emitted` webhook contract (`enforcement-v1`).
3. Optional loop-metrics JSON (know the null fields).
4. Who holds the `analyst` API key for export.

**What Tarka desk replaces:** leftover queue + Observe canary. Hunt only if a queryable graph is on (phase 2). **Not** Tableau.

### Q9 — Can packs sit beside Hive-published supervised scores without migrating models?

**Sit beside: yes, if the score is already on the evaluate payload. `VENDOR_SCORE_URL` is not a Hive connector and does not feed packs. ML sidecar is not AutoML and does not replace their microservices.**

| Path | Tip fact | Status |
|------|----------|--------|
| Buyer microservice keeps scoring; includes `score` on `POST …/evaluate` payload | Packs read **mapped registry fields**. Seed registry has **no** `vendor_score`. Overlay a `mapped_buyer` row on product Postgres, then author `when[].field`. | **PROVED after config** (payload + registry). Their Hive / microservices stay put. |
| `VENDOR_SCORE_URL` HTTP GET | Empty = off. 50ms timeout, fail-soft. Writes `vendor_score` / `vendor_decision` onto **`snap_extra` (receipt) after `evaluate_json_rules`** (`pipeline.py` ~909 vs ~1421). Packs have **already run**. Query is `tenant_id` + `entity_id` — not a Hive table scan. | **PARTIAL** — receipt overlay / sit-beside annotation. **Not** decide-time pack input. **Not** a Hive client. |
| `FEATURE_STORE_URL` L2 | Empty = off. Redis L1 ≠ production FS. | **PROVED after config** if they build an HTTP L2 in front of Hive. Not shipped. |
| Graph-risk / ring-score challenger | Offline holdout; serve off unless it beats `heuristic_v1`; live FLAG only via a **Promoted pack**. Compose URL unset. | **PROVED** as challenger. **MUST-NOT** as AutoML / model brain / migrate-off-Hive. |
| Tarka `ml-scoring` / ONNX examples | Optional overlay; skip on failure. | **MUST-NOT** as replacement for risk’s supervised fleet. |

**Org:** shared MLOps = Bedrock. Risk = supervised services + Hive. Tarka evaluate **reads** (payload) or **annotates** (URL slot). It does not train those models and does not require moving training off Hive / Bedrock / AWS.

### Q10 — Buyer Janus is skip-relations only. Is that Tarka graph?

**No. Do not assess as a rich queryable identity graph.** Empty `GRAPH_SERVICE_URL` is the honest phase-1 default. Wiring Tarka graph-service (AGE / Janus / Neo4j) + Hunt is a **pilot workstream**, not a free upgrade of their Janus.

| Buyer Janus (today) | Tarka hop / Hunt (tip) |
|---------------------|------------------------|
| Nodes largely **non-queryable** | Hop atoms need a **returned hop view** (`has_etype`, `has_multi_id`, `sibling_prior_flag`) from graph-service |
| **Skip** from **configured** relations only | Named edges (`USES_DEVICE`, …) on the receipt; empty URL → `graph:missing`, packs that need hops **do not fire** |
| Not arbitrary graph reads | `GRAPH_BACKEND=janusgraph` on Tarka graph-service is a **different** contract (Gremlin + indexes + subgraph). Pointing `GRAPH_SERVICE_URL` at their skip store without that contract is **not** proved |

Lite `make demo` **sets** `GRAPH_SERVICE_URL` to AGE (`docker-compose.lite.yml`). That is Tarka’s Day-1 Hunt demo — **not** their Janus. A buyer VPC clone that wants graph-off must empty the URL (or use a micro overlay). Leftovers nav **hides** when the desk graph URL is empty — frontline queue is then a phase-2 cost.

Hop packs (`USES_DEVICE` …) stay `mode=shadow` until Promote. They **cannot** assume skip-relations are enough. Treating skip as the brain while demo copy shows live multi-hop / Hunt person is **PARTIAL / theater**.

**Phase 1:** evaluate + JSON packs + receipts; graph URL **empty**; skip-relations may ride on the **payload** as enrichment (same sit-beside pattern as Hive scores).  
**Phase 2:** queryable graph URL (Tarka AGE, or graph-service in front of a **queryable** Janus) + Observe hop packs + Hunt. Their current skip-only Janus is enrichment, not that URL.

### Q11 — Drools + Groovy today. Drop-in, or parallel plane?

**Parallel plane / phased cutover. Tip must not claim Drools import.** `rules_import.py` loads **Tarka AST / JSON** into `engine_rules` — not `.drl` / Groovy. No Drools converter in-repo.

| Path | Tip honesty | Status |
|------|-------------|--------|
| Eng stands up Tarka evaluate + receipts + **1–N** JSON packs; Drools keeps serving residual | Same HTTP evaluate; buyer can dual-write or shadow-compare. `emit_only` default. | **PROVED** as coexistence shape. Wiring their traffic splitter is **their** eng. |
| Siloed Excel / Jupyter + Drools authors land first Observe packs **without** rewriting the estate | JSON is a **new** author language. Visual builder is product-skin (`RequireRole` RiskArchitect), still JSON under the hood. No `.drl` import. BYO LLM may **draft** Observe JSON (`authored_by=scout`); humans Promote. | **CONDITIONAL** — a few packs yes; whole estate **NO-GO**. |
| No-code / NLP replaces Drools | VISION: BYO scout drafts Observe; no closed omniscient loop; model never Promotes. Visual canvas ≠ Drools replacement. | **MUST-NOT-CLAIM**. Honest path: LLM drafts JSON Observe; Drools stays residual. |
| Replace Drools in 2 weeks | No importer; F3 Promote unsafe; siloed authors; no dual-run harness shipped | **NO-GO** unless a named dual-run is proved on **their** traffic (not on tip). |

`enforcement.mode=emit_only` is the honest dual-run default: Tarka receipts are advisory while Drools still enforces (or the reverse), until they contract handoff.

---

## 3. Claims vs pilot proof

Status key: **PROVED on clone/demo today** · **PROVED only after config** · **PARTIAL / theater** · **MUST-NOT-CLAIM**

| Claim | Where said | Proof on tip | Status |
|-------|------------|--------------|--------|
| `make doctor && make demo` Day-1 | README, clone-demo, CLAIM_LOCK | Scripts + offline CI | **PROVED** (scripts). **PARTIAL** (no compose e2e CI). Host `5432`/`6379` friction. |
| ELv2 source-available, not OSS; beta, no GA | README, LICENSE, SUPPORT | LICENSE + CI phrase gate | **PROVED** |
| Rust evaluate + receipts + pack-why | README, VISION | tarka-core + walk + packWhy tests | **PROVED** (API). **PARTIAL** on desk (F1). |
| Observe ≠ live; human Promote; auto-promote default off; model never Promotes / evaluates | README, CLAIM_LOCK | Provision default; 409 `never_auto_promote`; hop `mode=shadow` | **PROVED** (API). **PARTIAL** (F3 UI). |
| Empty `GRAPH_SERVICE_URL` = hops off | README, PlaneOff | `graph:missing` tests | **PROVED**. Leftovers hidden if desk graph URL empty. Lite demo **turns AGE on** — buyer phase-1 must empty the URL. |
| Hop / `USES_DEVICE` Observe-until-Promote | Hop JSON, CI | `test_hop_packs_stay_shadow` | **PROVED** as Observe packs on Tarka hops. **PARTIAL** vs buyer skip-only Janus — not a substitute. |
| Buyer Janus skip-relations = Tarka graph / Hunt | (buyer stack) | graph-service Janus adapter is a different Gremlin contract | **MUST-NOT-CLAIM**. Connecting graph is a workstream. |
| Enforcement default emit-only | enforcement-v1 + runtime | `test_enforcement_authority.py` | **PROVED** (runtime). |
| GitLab-grade G0–G9 | production-install-v1, soak | G0–G8 landed. G9 **unsigned** | **MUST-NOT-CLAIM** the grade |
| OIDC optional; digests; helm honesty; secrets 503; NetPol/SM; backup drill docs; SUPPORT intent | CLAIM_LOCK, G1–G8 | CI + docs | **PROVED only after config** (as documented). Grade still off. |
| BYO LLM / no omniscient loop | VISION, CLAIM_LOCK | Factory; empty URL off | **PARTIAL** — Q4. Closed loop **MUST-NOT**. |
| L2 leftover → Observe; FP soften | CLAIM_LOCK | API tests | **PROVED** (API). **PARTIAL** (F2; late-label webhook-only). |
| ML sidecar / graph-risk challenger | CLAIM_LOCK, gnn-label-loop | URL unset; Promote-shaped | **PROVED** as off challenger. **MUST-NOT** GNN live / AutoML / replace Hive. |
| `vendor_score` URL slot; empty = off | CLAIM_LOCK, vendor-score-slot-v1 | `vendor_score.py`; empty/timeout tests | **PARTIAL** — receipt after packs; not Hive; not pack input |
| Packs sit beside buyer scores | (buyer need) | Payload + field registry | **PROVED after config**. URL slot alone is not enough. |
| Warehouse export; buyer owns lake | warehouse-sink-v1 | `GET /v1/exports/receipts` | **PROVED after config**. No BQ/Hive host. |
| Bake-off / loop-metrics feed BI | bakeoff-metrics-v1, LoopScoreboard | API + desk chrome; some fields null | **PARTIAL**. Desk ≠ Tableau. |
| Weekly analytics scorecard | scripts/analytics README | **Stub** | **PARTIAL / theater** |
| Tarka replaces Tableau / Hive / supervised microservices / Bedrock training | (buyer risk) | — | **MUST-NOT-CLAIM** |
| Users / LOI / ARR / OSS / 1.9B TPS | README must-not | CI banned phrases | **MUST-NOT-CLAIM** |
| Microsoft Copilot / BI Gemini as Tarka author plane | (buyer assumption) | No connector | **MUST-NOT-CLAIM** |
| Multi-party marketplace SKU | graph-planes `parties[]` | Persist + honesty test | **PARTIAL** |
| Excel / Jupyter → pack | (buyer ops) | No importer | **UNPROVED** / **MUST-NOT** as shipped |
| Drop-in Drools / Groovy import | (buyer rule base) | `rules_import.py` is Tarka AST/JSON only | **MUST-NOT-CLAIM** |
| JSON packs as parallel plane beside Drools | README / rules.md | Rust JSON evaluate; emit-only | **PROVED** (Tarka side). Dual-run harness **UNPROVED**. |
| No-code NLP replaces Drools | (buyer risk / VISION scout) | Scout drafts Observe; human Promote | **MUST-NOT-CLAIM** |
| Replace Drools estate in 2 weeks | (buyer wish) | — | **MUST-NOT-CLAIM** / **NO-GO** |
| Tarka raises Hive FI (mid-60s → 80) or detects more than ~7% GMV | (buyer KPI risk) | Evaluate plane operates already-detected loss; no model training | **MUST-NOT-CLAIM** |

---

## 4. Pilot walkthrough gaps (desk)

| Step | Tip | Blocker for |
|------|-----|-------------|
| Leftover REVIEW | Hidden if graph URL empty | Frontline on evaluate-only |
| Receipt-why | Analyst audit **403** → PackWhyStrip missing. **F1 OPEN.** | **Frontline** |
| Override + why | Create draft `"desk skip"`. **F2 OPEN.** | **Frontline / strategy** |
| Promote confirm | One-click + `/observe` bypass. **F3 OPEN.** | **Strategy** |
| Pack findability | Text id only | Siloed strategy |
| Late-label | Webhook only | Needs processor / Hive job — **good** for BI; no desk form |
| Excel → pack | Does not exist | Strategy culture |
| Tableau | No connector; export/webhook only | BI (eng must wire) |
| Hunt / hop why | Needs queryable graph URL | Phase 2. Skip-Janus ≠ hop brain |
| Drools → JSON | No importer | Eng translator or BYO draft Observe |

---

## 5. Thin / scaffold / fail-soft

| Surface | What it is |
|---------|------------|
| F1 / F2 / F3 | Open scorecard holes (separate UI agent). |
| `VENDOR_SCORE_URL` | Looks like “packs read their score.” Fetch is **post-pack**, receipt-only, 50ms, not Hive. |
| VISION Azure / Vertex / Bedrock | Named backends **refuse**. OpenAI-compat only. |
| `COPILOT_*` | Not Microsoft Copilot. |
| LoopScoreboard / `/analytics` | Desk theater if sold as leadership KPI. |
| `export_weekly_scorecard_json.py` | Documented stub. |
| ClickHouse / Grafana | Optional ops, not Tableau. |
| Ring / GNN | Challenger; no HTTP ring job API. |
| Doctor `5432`/`6379` | First lean-eng stall. |
| Helm `prod-on-k8s` | Evaluate HA; desk **OFF**. |
| G9 sheet | Unsigned. Landing ≠ grade. |
| Marketplace demo tenant | Fixture. |
| Lite AGE + Hunt `NEXT:` | Demo implies graph-on Day-1. Buyer Janus is skip-only. Empty URL is the honest VPC start. |
| Tarka `GRAPH_BACKEND=janusgraph` | Queryable Gremlin + indexes — **not** their skip-relation store. |
| Visual / NLP author | Product canvas + BYO scout draft Observe. Still JSON. Not Drools import. |

---

## 6. Post-gap W1–W8

**No locked W-week plan file in the tree.** Breakdown lives in GitHub PR **#404**. Do not confuse with **G0–G9**.

| Week | Tip |
|------|-----|
| W0–W5, W7–W8, OPT vendor_score | **Landed** (contracts + tests; W1/W3/W7 unlabeled in-tree) |
| W6 ring | **PARTIAL** — helper + tests; no HTTP API |
| W2/W8 contract prose | Still says “implements in W*” — stale |

---

## 7. Go / no-go (CUT / MODULES / BAU / FAIL)

| Ask | Verdict | Until / condition |
|-----|---------|-------------------|
| **CUT** — tip promises a concrete BAU improvement (iterate / why, not FI/GMV) | **CONDITIONAL PASS** | Eng-led JSON Observe→Promote + API receipt-why. **FAIL** if BAU is already stable. |
| **MODULES** — few modules vs full stack | **FEW** | Evaluate + JSON packs + receipts + override why. Graph / Hunt / Advise / Tableau / case CRM **OUT**. |
| **BAU** — parallel plane, no cutover | **YES** | `emit_only`; Drools live; Hive enrichment; Tableau stays BI; graph URL empty. |
| **FAIL** — FI-to-80 or detect-more-GMV | **MUST-NOT** | Wrong plane. 7% is their coverage. |
| **FAIL** — rip-replace Drools + Hive + Janus + Tableau | **NO** | No importer. Wrong modules. |
| **FAIL** — desk leftover / Promote as week-1 | **NO** until F1–F3 | Receipt-why 403; leftover draft without why; silent Promote. |
| **GitLab-grade install** | **MUST-NOT** | Signed G9 on a **named** pilot. |

**Anoop one-liner:** CUT: conditional PASS on faster pack/iterate (eng JSON Observe→Promote) + API receipt-why — FAIL FI/GMV and FAIL if Drools+Hive+Tableau+Janus BAU is already stable. MODULES: evaluate + JSON packs + receipts + override why (beside Drools); graph/Hunt/Advise/Tableau OUT. BAU: emit-only shadow/Observe, Drools live, Hive enrichment, no cutover. Desk leftover/Promote FAIL until F1–F3.

---

## 8. Remediation before kickoff (blocker first)

1. **F1** — Receipt pack-why on `minimal` when analyst 403s.
2. **F3** — Confirm Promote; close `/observe` bypass.
3. **F2** — Mandatory why on Create draft.
4. **Score sit-beside** — If packs must use Hive scores: publish onto evaluate **payload** + registry map. Do not sell `VENDOR_SCORE_URL` as decide-time Hive. Optional: thin HTTP adapter later (still post-pack today).
5. **BI handoff** — Eng delivers receipt export + `evaluation_token` + optional `decision.emitted`. Do not pitch desk Analytics as Tableau.
6. **BYO copy** — Bedrock/Azure/Vertex = OpenAI-compat URL or off. No Copilot plane. (CLAIM_LOCK + INDEX Advise tightened this PR.)
7. **Excel/Jupyter + Drools** — Budget an eng translator to **1–N** JSON Observe packs. No `.drl` / Groovy importer. Do not sell NLP as Drools replacement.
8. **Graph** — Phase 1 empty URL. Skip-Janus as payload enrichment only. Hop/Hunt later.
9. **Doctor ports / multi-party vtypes / buyer TPS** — as needed; not week-1 grade.
10. **G9** — Only if they later want a grade claim.

UI F1–F3 are a **separate** agent. This PR does not fix them.

---

## 9. Locks

- No named incumbents as analogues. No “X-class” copy in claims.
- No invented users, LOI, or ARR.
- GitLab-grade **OFF** without signed G9 soak on a named pilot.
- Model never evaluates or Promotes. `emit_only` default.
- ELv2, not OSS. Beta, no GA. No Tarka-sold tokens.
- Empty plane URL = off.
- Tarka does not replace Tableau, Hive, supervised microservices, Bedrock training, skip-only Janus, or the Drools/Groovy estate.
- Do not claim Tarka raises buyer FI or detected-loss GMV %. Chargeback / guarantee is not the SKU.
- Shared MLOps ≠ risk supervised services ≠ BI.

---

## Sources (tip)

- Buyer-facing: [`README.md`](../../README.md), [`VISION.md`](../../VISION.md), [`SUPPORT.md`](../../SUPPORT.md), [`docs/INDEX.md`](../INDEX.md), [`CLAIM_LOCK.md`](./CLAIM_LOCK.md)
- Contracts: `production-install-v1`, `warehouse-sink-v1`, `label-join-v1`, `vendor-score-slot-v1`, `feature-store-posture-v1`, `bakeoff-metrics-v1`, `enforcement-v1`
- Score / ML: `services/decision-api/src/decision_api/vendor_score.py`, `evaluate/pipeline.py` (rules ~909, vendor fetch ~1421), `docs/docs/guides/gnn-label-loop.md`
- Export / BI: `receipt_export.py`, `frontend/src/components/LoopScoreboard.tsx`, `scripts/analytics/README.md`
- LLM: `services/shadow_agent/providers/factory.py`, `llm_client.py`
- Desk holes: `Decisions.tsx`, `Leftovers.tsx`, `OpsShadow.tsx`, `ShadowMode.tsx`, `L2DraftButtons.tsx`
- Honesty CI: `test_walk_receipts.py`, `test_postgap_contracts.py`, `test_production_install_soak_checklist.py`
