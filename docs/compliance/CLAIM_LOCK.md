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
| AI / trend ops | [`docs/docs/guides/repo-productionization-runbook.md`](../docs/guides/repo-productionization-runbook.md) |
| Control narrative (not a cert) | [`soc2-pci/`](./soc2-pci/) |
| Enforcement | [`docs/contracts/enforcement-v1.md`](../contracts/enforcement-v1.md) |
| Label join | [`docs/contracts/label-join-v1.md`](../contracts/label-join-v1.md) |
| Bake-off metrics | [`docs/contracts/bakeoff-metrics-v1.md`](../contracts/bakeoff-metrics-v1.md) |
| Queue connectors | [`docs/contracts/queue-seam-v1.md`](../contracts/queue-seam-v1.md) — connectors only; not a case CRM |
| Feature store posture | [`docs/contracts/feature-store-posture-v1.md`](../contracts/feature-store-posture-v1.md) |
| Graph planes | [`docs/contracts/graph-planes-v1.md`](../contracts/graph-planes-v1.md) |
| Production / GitLab-grade install | [`docs/contracts/production-install-v1.md`](../contracts/production-install-v1.md). Empty digest ≠ immutable pin. |
| `prod-on-k8s` preset | Overlay exists ≠ GA / GitLab-grade. Digest pin + no sqlite/`emptyDir` for decisions/audit/labels/packs. See production-install-v1. |

Historical “maturity 4.x” scorecards and competitive matrices were removed in the docs cleanup.

## Tip claims (after #392–#397)

Buyer-facing README / Day-1 / hop / GNN copy must match this table. Do not advertise the right-hand column as shipped.

| True on tip | Must not read as shipped |
|-------------|--------------------------|
| ELv2 source-available (not OSS). Beta, no GA | Open-source; ready-for-beta testers; unattended merchant beta |
| `make doctor && make demo`. Rust evaluate + receipts + pack-why | Model ALLOW / DENY; Tarka-branded model |
| Observe ≠ live until promote gates pass. Ungated → human Promote. Gates defined+met → may auto-Promote (default off). Human Propose Demote → Confirm. Model never Promotes or demotes. Empty URL / model never demotes. | Live hop FLAG without Promote; always-on Day-1 auto-Promote; auto-demote |
| Hop packs `mode=shadow`. Live only after promote gates pass (same gated-or-human rule). | Always-on graph; “every evaluate is on the graph”; GNN live / GNN god-model |
| Enforcement contract-gated; default emit-only ([enforcement-v1](../contracts/enforcement-v1.md)). | Handoff as Day-1 default; silent block in emit-only |
| Queue webhook empty = off. Leftovers residual. | Case CRM; Tarka-hosted ticket DB |
| Redis L1 ≠ production online FS. Empty `FEATURE_STORE_URL` = L2 off. | Feast-class / production FS from Redis alone |
| Offline ring jobs → Observe proposals. Not GNN live. | Identity-as-SKU; live hop FLAG without Promote |
| Optional `vendor_score` is a buyer URL slot. Empty URL = off. | Bundled third-party score SKU |
| Empty `GRAPH_SERVICE_URL` ≠ sibling identity (`graph:missing`) | Closed omniscient AI author loop |
| L2 leftover/override → Observe draft; AI backtest **required** before Observe | Case CRM |
| FP late-label → Observe soften draft (#394) | Consortium SKU |
| Beachhead Observe seeds (promo / COD / payout) seed ≠ live. Not banks | Users / LOI / ARR as traction |
| Graph-risk / ring-score challenger (#397). `GRAPH_GNN_BETA_URL` unset in compose | GNN live |
| `prod-on-k8s` is core-api HA (external PG/Redis). Generate requires `--digest-map` (`sha256:<64-hex>`) for a grade claim. Empty digest (`--allow-empty-digest`) is a limitation / non-grade `helm template`, not an immutable image. No sqlite/`emptyDir` for decisions/audit/labels/packs in production-labeled presets. See [production-install-v1](../contracts/production-install-v1.md). | GitLab-grade already achieved; GA from preset; in-cluster PG/Redis as production; mutable tag as the recommended prod pin |
| CI `helm_prod_honesty` fails sqlite / durable emptyDir / in-cluster PG on `prod-on-k8s` and `enterprise-desk-on-k8s` (G1 beachhead) | GitLab-grade complete production install; every `environment: prod` overlay scanned |
| CI `helm_prod_digest_honesty` **fails** empty digest on the prod-on-k8s honesty / publish path. Lite/demo are not this path. | Empty digest as a grade / immutable claim |
| Prod/enterprise examples use `secretKeyRef` (no reusable default passwords). Empty `API_KEYS` + empty OIDC + insecure off → 503. Matrix: [production-install-v1](../contracts/production-install-v1.md) | Vault/ESO required; open evaluate when secrets missing; GitLab-grade already achieved |

**Provision warning:** `shadow_auto_promote` exists as a tenant file + host gate (`auto_promote` defaults **False**). Never advertise always-on auto-Promote as Day-1. Enabling requires explicit tenant promote gates (thresholds already in the provision file).
