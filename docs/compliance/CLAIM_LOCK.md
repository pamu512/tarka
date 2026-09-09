# Claim lock (honesty)

**Rule:** Do not advertise live-tenant, certified SOC2/PCI, or product-wide maturity scores from fixture CI, waived partner proofs, or deleted score matrices.

## Allowed language

- Offline / fixture holdouts and golden corpora prove **wiring and gates**, not named live tenants.
- **Observe** = observe-only evaluate (`metadata.shadow`) + pack canary; **Advise** = LLM copilot (investigation, Shadow agent, trend) — advise only, never decides. decision-api **decides**.
- Partner fusion and enrichment are honest only when credentials and sinks are real; otherwise degrade (503 / WAIVED), never invent success.
- Vertical packs and kill-criteria gates are installable locally; empty tenant ≠ demo SHA proof.

## Source of truth

| Topic | Doc |
|-------|-----|
| Feature authority | [`docs/docs/guides/feature-data-flows.md`](../docs/guides/feature-data-flows.md) |
| Receipt pack-why | Desk `PackWhyStrip`: leftover REVIEW → receipt → in-context why. Analyst audit 403 falls back to minimal (real pack-why). Never invent why. Leftover/decision vocab stays **REVIEW**, not a FLAG rename. |
| AI / trend ops | [`docs/docs/guides/repo-productionization-runbook.md`](../docs/guides/repo-productionization-runbook.md) |
| Control narrative (not a cert) | [`soc2-pci/`](./soc2-pci/) |
| Enforcement | [`docs/contracts/enforcement-v1.md`](../contracts/enforcement-v1.md) |
| Label join | [`docs/contracts/label-join-v1.md`](../contracts/label-join-v1.md) |
| Warehouse consume | [`docs/contracts/warehouse-sink-v1.md`](../contracts/warehouse-sink-v1.md) — buyer-owned job; Tarka exports joinable receipts+labels. Optional consume of joined labels since T may propose Observe drafts (`authored_by=seed`). Promote only via existing gates / human. Never auto-Promote / never auto Active. Not a hosted lake. Not CRM. Not a case inbox. |
| Label horizons | [`docs/contracts/label-join-v1.md`](../contracts/label-join-v1.md) — tenant policy **examples** (promo FP days / collusion window / chargeback ~90d). Not Tarka morals. Not a chargeback-guarantee SKU. Never auto-demote from horizons. |
| Bake-off metrics | [`docs/contracts/bakeoff-metrics-v1.md`](../contracts/bakeoff-metrics-v1.md) — `pack_metrics[]` (`tarka.pack_metrics/v1`) names `rule_hit_rate` / `shadow_divergence`; **null = unknown**. API fills from Observe logs when present. Promote confirm binds the pack row or honest empty. Shared with Suggest Propose Demote. GLOBAL `evaluate_count` / `action_mix` / `shadow_divergence` fill from audit/receipts/shadow pairs when present (D8.2). **null = unknown**. LoopScoreboard binds real numbers or — + English reason (D8.3). Same `tarka.loop_metrics/v1` payload: filling one side must not clobber the other. Do not mint `tarka.loop_metrics/v2` or fork pack-metrics. share-with-M3; do-not-double-implement. |
| Join-rate glass | [`docs/contracts/bakeoff-metrics-v1.md`](../contracts/bakeoff-metrics-v1.md) — `join_rate` / `labeled_receipt_rate` on `tarka.loop_metrics/v1`. **null = unknown** (never 0% theater). Fuel names M2 may read later; tick still suggests from `pack_metrics[]`. Buyer owns the lake. Not CRM. Horizons are tenant policy examples. Never auto-demote from join rate. |
| Effectiveness tick | Suggests Propose Demote with pack metrics only. Propose→Confirm Demote human-only; auto-demote forbidden; model never demotes. Tick cannot confirm. |
| Queue connectors | [`docs/contracts/queue-seam-v1.md`](../contracts/queue-seam-v1.md) — connectors only; not a case CRM |
| Pack promote export | [`docs/contracts/pack-promote-export-v1.md`](../contracts/pack-promote-export-v1.md) — `tarka.pack_promote_export/v1` after desk Promote. Desk Promote is live SoT / go-live. Git / export is backup. Sample consume: [`docs/examples/pack-promote-export-consumer.md`](../examples/pack-promote-export-consumer.md). Empty consumer URL = outbound off. |
| Feature store posture | [`docs/contracts/feature-store-posture-v1.md`](../contracts/feature-store-posture-v1.md) |
| Field registry | [`docs/docs/guides/field-registry-onboarding.md`](../docs/guides/field-registry-onboarding.md) — product Postgres `field_registry` / `field_maps`; demo file/fixture + PUT 403. Windows on `counter_manifest`. Not G1.3 PIT serve. |
| Graph planes | [`docs/contracts/graph-planes-v1.md`](../contracts/graph-planes-v1.md) |
| Hunt depth | [`docs/contracts/hunt-depth-v1.md`](../contracts/hunt-depth-v1.md) — D7.4 Path B enforced depth-1; `hunt_depth_max=1`; empty `GRAPH_SERVICE_URL` = Hunt/hops off; `/v1/subgraph` emits `depth_requested` / `depth_applied` / `degrade_reason`. Operator day-1: [graph-analysis](../docs/guides/graph-analysis.md#day-1-hunt-depth). Regression: [hunt-depth-regression](../testing/hunt-depth-regression.md) |
| Production / GitLab-grade install | [`docs/contracts/production-install-v1.md`](../contracts/production-install-v1.md). Empty digest ≠ immutable pin. |
| `prod-on-k8s` preset | Overlay exists ≠ GA / GitLab-grade. Digest pin + no sqlite/`emptyDir` for decisions/audit/labels/packs. See production-install-v1. |
| Production upgrade / rollback | [`docs/docs/guides/production-upgrade.md`](../docs/guides/production-upgrade.md) — helm digest pin, expand/contract schema, pack fail-closed. Not multi-region. |
| Commercial install pack / support claims | [`SUPPORT.md`](../../SUPPORT.md) — VPC / Helm / SSO / pack-GitOps assist + severity **intent**. Not a 99.99% SLA. |
| GitLab-grade install claim (G9) | Allowed **only** when G0–G8 have landed **and** [`docs/docs/guides/production-install-soak-checklist.md`](../docs/guides/production-install-soak-checklist.md) is **signed** for a **named** pilot (internal or buyer). This row is not the grade. Separate from “primary decisioner” maturity. |

Historical “maturity 4.x” scorecards and competitive matrices were removed in the docs cleanup.

## Tip claims (after #392–#397)

Buyer-facing README / Day-1 / hop / GNN copy must match this table. Do not advertise the right-hand column as shipped.

| True on tip | Must not read as shipped |
|-------------|--------------------------|
| ELv2 source-available (not OSS). Beta, no GA | Open-source; ready-for-beta testers; unattended merchant beta |
| `make doctor && make demo`. Rust evaluate + receipts + pack-why | Model ALLOW / DENY; Tarka-branded model |
| Observe ≠ live until promote gates pass. Ungated → human Promote. Gates defined+met → may auto-Promote (default off). Propose→Confirm Demote human-only; auto-demote forbidden; model never demotes. Empty URL / model never Promotes. | Live hop FLAG without Promote; always-on Day-1 auto-Promote; auto-demote |
| Desk Promote is live SoT / go-live. Git / `tarka.pack_promote_export/v1` is backup after Promote. Write fail does not undo Promote. | Git merge as go-live gate; export as Promote authority; missing export as demote |
| Hop packs `mode=shadow`. Live only after promote gates pass (same gated-or-human rule). | Always-on graph; “every evaluate is on the graph”; GNN live / GNN god-model |
| Enforcement contract-gated; default emit-only ([enforcement-v1](../contracts/enforcement-v1.md)). Outbound decision/action webhooks HMAC-SHA256 signed (`x-tarka-signature`) when secret is set. Empty URL = plane off. Suggested-action `action_id` is hex SHA-256 of tenant + trace_id + action token + pack hash — stable across retries, not a random UUID per POST. Inbound product ACK binds delivery status to `trace_id` + `action_id` (queryable). ACK is not Promote/Demote and not a case inbox. | Handoff as Day-1 default; silent block in emit-only; unsigned enforcement webhooks as the contract; random `action_id` per POST; ACK as Promote/Demote; case CRM from ACK; desk delivery glass as this slice (G4.4) |
| Queue webhook empty = off. Leftovers residual. | Case CRM; Tarka-hosted ticket DB |
| Redis L1 ≠ production online FS. Empty `FEATURE_STORE_URL` = L2 off. Optional L2 PIT serve when the URL is set; evaluate fail-soft on miss/timeout; receipt `feature_source` matches the path used. L2 does not decide ALLOW/DENY. `feast_class_claim_allowed` stays false. | Feast-class / production FS from Redis alone |
| Optional L2 writers (evaluate-seen stream + warehouse/export jsonl backfill). Empty `FEATURE_STORE_URL` = no L2 writes. Writer fail-soft; evaluate still decides and does not wait on writer lag. | Named stream-processor SKU; evaluate blocked on writer lag; Feast-class writers |
| Golden PIT: replay at T (`as_of=T`) matches frozen features; later snapshots do not leak (no future leak). `holdout_split` is sidecar/offline ML export only — training excludes `as_of >= cutoff`. Model never ALLOW/DENY/Promote/demote. `feast_class_claim_allowed` stays false. `GRAPH_GNN_BETA_URL` unset stays off. | Feast; AutoML that ALLOW/DENYs; model decides; GNN live |
| Product field-registry overlays and maps persist in Postgres (`field_registry`, `field_maps`). Demo is seed file/fixture; PUT 403. Windows stay on `counter_manifest`. | Durable registry on demo; windows in the registry; Redis as feature-def SoT |
| Offline ring jobs: export subgraph+labels → ring_score/tags JSON (async sidecar). Writer publishes tags as Observe drafts (`mode=shadow`, `authored_by=seed`). Never auto Active. Never on evaluate. Empty GRAPH_SERVICE_URL hops still off. Not GNN live. | Identity-as-SKU; live hop FLAG without Promote; GNN live from ring job; auto Active from ring tags |
| Optional `vendor_score` is a buyer URL slot. Empty URL = off. | Bundled third-party score SKU |
| Empty `GRAPH_SERVICE_URL` ≠ sibling identity (`graph:missing`) | Closed omniscient AI author loop |
| D7.4 Path B: AGE Hunt enforced depth-1 (`hunt_depth_max=1`). Empty `GRAPH_SERVICE_URL` = Hunt/hops off. `/v1/subgraph` emits `depth_requested` / `depth_applied` / `degrade_reason` (`tarka.hunt_depth/v1`). Requested > applied → `hunt:depth_capped`; walk stays 1. | Unlimited Hunt path; variable-length path product; Hunt as identity SKU; invented neighbors when URL empty; GA multi-hop without `depth_applied` |
| L2 leftover/override → Observe draft; AI backtest **required** before Observe | Case CRM |
| FP late-label → Observe soften draft (#394) | Consortium SKU |
| Optional consume of joined warehouse labels since T → Observe drafts (`authored_by=seed`). Promote only via existing gates / human. Never auto Active. | Case CRM / dispute inbox; auto Active from labels |
| Beachhead Observe seeds (promo / COD / payout) seed ≠ live. Not banks | Users / LOI / ARR as traction |
| Community = GitHub issues (no SLA). Commercial pack = VPC / Helm / SSO / pack-GitOps assist + severity intent ([SUPPORT.md](../../SUPPORT.md)) | 99.99% (or any nines) as a Tarka SLA; SOC 2 from us; hosted Tarka Cloud; GitLab-grade from SUPPORT.md |
| Graph-risk / ring-score challenger (#397). `GRAPH_GNN_BETA_URL` unset in compose | GNN live |
| `prod-on-k8s` is core-api HA (external PG/Redis). Generate requires `--digest-map` (`sha256:<64-hex>`) for a grade claim. Empty digest (`--allow-empty-digest`) is a limitation / non-grade `helm template`, not an immutable image. No sqlite/`emptyDir` for decisions/audit/labels/packs in production-labeled presets. See [production-install-v1](../contracts/production-install-v1.md). | GitLab-grade already achieved; GA from preset; in-cluster PG/Redis as production; mutable tag as the recommended prod pin |
| CI `helm_prod_honesty` fails sqlite / durable emptyDir / in-cluster PG on `prod-on-k8s` and `enterprise-desk-on-k8s` (G1 beachhead) | GitLab-grade complete production install; every `environment: prod` overlay scanned |
| CI `helm_prod_digest_honesty` **fails** empty digest on the prod-on-k8s honesty / publish path. Lite/demo are not this path. | Empty digest as a grade / immutable claim |
| Prod/enterprise examples use `secretKeyRef` (no reusable default passwords). Empty `API_KEYS` + empty OIDC + insecure off → 503. Matrix: [production-install-v1](../contracts/production-install-v1.md) | Vault/ESO required; open evaluate when secrets missing; GitLab-grade already achieved |
| Soak checklist exists (G9). “GitLab-grade install” only after G0–G8 **and** a named-pilot sign-off. Not primary decisioner. Beta, no GA, no SOC 2 from us. | GitLab-grade already achieved; primary decisioner; SOC 2 / PCI cert; GA from this file or from `prod-on-k8s` existing |
| `/ops/bakeoff` + LoopScoreboard = tenant GLOBAL `evaluate_count` / `action_mix` / `shadow_divergence` (**null = unknown**). Promote confirm = `pack_metrics[]` row or honest empty (M3). Suggest Propose Demote shares the pack row (M2). Same `tarka.loop_metrics/v1`; sides do not overwrite. Do not mint `tarka.loop_metrics/v2`. Thresholds are tenant policy. | CRM bake-off dashboard; fake 0%; forked pack-metrics schema |
| VisualRuleBuilder is a leftover canvas, not a product SKU. SentencePackPanel is thin no-code (same pack JSON evaluate already runs). | VisualRuleBuilder as a SKU / no-code product |

**Provision warning:** `shadow_auto_promote` exists as a tenant file + host gate (`auto_promote` defaults **False**). Never advertise always-on auto-Promote as Day-1. Enabling requires explicit tenant promote gates (thresholds already in the provision file).
