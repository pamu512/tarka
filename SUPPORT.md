# Support

Tarka application code is **source-available** under the **Elastic License 2.0** (not open-source). You may run it on your own metal or VPC for your own fraud operations. You may not provide Tarka to third parties as a hosted or managed service. There is **no hosted Tarka Cloud** for resale.

**Status:** beta. There is no GA tag. Development is on `master`.

Two tracks. Do not smash them.

| Track | Who | What you get |
|-------|-----|----------------|
| **Community** | Anyone who cloned | [GitHub issues](https://github.com/pamu512/tarka/issues). Best-effort. **No SLA**, **no paid channel**, **no on-call**, **no incident bridge**. |
| **Commercial install pack** | Named beachhead buyer (purchase) | VPC install assist, Helm values review, SSO wiring, pack GitOps export help, and severity-class **response intent**. Not an availability percentage. |

Honesty lock: [CLAIM_LOCK](docs/compliance/CLAIM_LOCK.md). Grade contract: [production-install-v1](docs/contracts/production-install-v1.md). Day-1 skins: [README](README.md) · [product Day-1](docs/docs/guides/product-day1-install.md).

---

## Community

Best-effort via [GitHub issues](https://github.com/pamu512/tarka/issues). That is not a production support contract.

### How to file an issue

Include:

- **service** (for example `core-api` / decision-api, case-api, investigation-agent)
- **tenant** (or `demo` / local)
- **trace_id** from the evaluate or case response
- What you expected versus what happened
- Compose files or Helm preset (`fraud-desk`, `prod-on-k8s`, …)
- Branch or commit SHA (development is on `master`)

Do not file undisclosed security vulnerabilities as public issues — see [SECURITY.md](SECURITY.md).

---

## Commercial install pack (GitLab-shaped self-host)

What a buyer **purchases**. This is not a SaaS desk, not a hosted tenant, and not GitLab-grade by itself. Beachhead is CE-shaped VPC evaluate-HA on last-mile / food / q-comm / gig / retail — not banks as P0.

We help **you** install. We do not operate your cluster.

### In the pack

| Item | What we do | What we do not do |
|------|------------|-------------------|
| **VPC install assist** | Walk an operator through CE-shaped `prod-on-k8s` (or product compose) on **their** VPC: external Postgres + Redis, secrets, digest pin. | Run the cluster. Provide Tarka as a hosted or managed service. Invent in-cluster PG/Redis as production. |
| **Helm values review** | Review buyer values against the production-install gates (no sqlite / `emptyDir` for decisions, audit, labels, or packs; no leftover default passwords). | Apply the chart for you as a managed service. Treat a green `helm template` as the grade. |
| **SSO wiring** | Wire OIDC for **desk humans** via first-class Helm `coreApi.oidc.{issuer,audience,jwksUrl,rolesClaim}`. `OIDC_CLIENT_ID` stays extraEnv; `OIDC_CLIENT_SECRET` on `global.appSecretsName`. Empty issuer stays local / API-key mode. | Become the IdP. Replace machine `API_KEYS` with OIDC. Require OIDC to boot evaluate. Require SAML. |
| **Pack GitOps export help** | Help consume `tarka.pack_promote_export/v1` after desk Promote ([pack GitOps](docs/docs/guides/pack-gitops.md)). Git is backup/export. | Require a git PR to go live. Desk Promote remains the live source of truth. |
| **Severity response intent** | Classed first-response **intent** on a **named** pilot (table below). | An uptime SLA. **99.99%** (or any nines) as a Tarka promise. Operator SLO targets in [service-slos-v1](docs/docs/guides/service-slos-v1.md) are **buyer-owned**. |

OIDC is optional. API keys stay the machine / evaluate path. `coreApi.oidc.*` is SoT (not extraEnv-only). Production + a non-empty issuer requires resolved Redis (no in-process OIDC state fallback). See [deployment.md](docs/docs/guides/deployment.md).

### Severity response intent

Intent, not a contract. No response-time hours and no availability nines live in this file — those would be fake SLAs. The purchased window (hours the pack engineer is on) is set at purchase, not here.

| Class | Meaning | Intent |
|-------|---------|--------|
| **Sev-1** | Evaluate path down on the named pilot (`core-api` / decision-api cannot serve evaluate) | First human response when a pack engineer is available in the purchased window |
| **Sev-2** | Degraded evaluate, or install-blocking (OIDC, secrets, Helm render) on that pilot | Same window, after Sev-1 |
| **Sev-3** | Pack GitOps export, values questions, how-to | Queued in the purchased window |

Buyer-operated burn alerts and [incident-response](docs/docs/guides/incident-response.md) stay on the buyer’s stack. This pack is not that runbook.

Named-pilot buyers get a private channel **at purchase**. Until a pack is purchased, use community GitHub issues. This repository does not invent a sales inbox.

---

## Limitation table

| Limit | Honest statement |
|-------|------------------|
| **Beta, no GA** | Product and Helm tags are beta. `1.3.0-beta` is a mutable tag. Digest pin is required before a grade claim. Not ready-for-beta testers; not unattended merchant beta. |
| **No SOC 2 from us** | [`docs/compliance/soc2-pci/`](docs/compliance/soc2-pci/) is a control-mapping suite for *your* readiness work. It is **not** a SOC 2 Type II report, not a PCI ROC, and not a cert from Tarka. Buyer owns attestation. |
| **No consortium** | No consortium SKU. Any adapter talks to **your** decision-api. |
| **No case CRM** | Leftovers + Hunt are residual. [Queue seam](docs/contracts/queue-seam-v1.md) is connectors only. Tarka does not host a ticket DB. |
| **Buyer owns warehouse / queue** | Postgres, Redis, object store, NATS/queue, and warehouse are buyer-operated. Empty plane URL = that plane off. We do not sell those as a Tarka Cloud. |
| **No hosted Tarka Cloud** | ELv2 forbids providing Tarka as a hosted or managed service to third parties. `infra/deploy/hosted/` is one-tenant pilot scaffolding, not a resale SKU. |
| **Beachhead CE** | last-mile / food / q-comm / gig / retail. Not banks as P0. `prod-on-k8s` is core-api HA (frontend **OFF**, Shadow **OFF**) — not the product desk. |
| **Grade not claimed here** | GitLab-grade only after G0–G8 land **and** a **named** beachhead pilot passes the G9 checklist. This file is G8 (support pack). It is not G9 and not the grade. |

Do not read this page as users, LOI volume, or ARR.

---

## Investor / LOI paragraph

Tarka sells a commercial **self-host install pack** for a GitLab-shaped VPC CE: assist on the buyer’s cluster, Helm values review, optional OIDC wiring for desk humans, pack GitOps export help, and severity-class response intent. The software is Elastic License 2.0 source-available (not open-source); there is no hosted Tarka Cloud to resell; beachhead is CE evaluate-HA on last-mile / food / q-comm / gig / retail, not banks. Beta, no GA, no SOC 2 from us, no consortium SKU, no case CRM; the buyer owns warehouse and queue. This paragraph is not traction, user counts, LOI volume, or ARR.

---

## production-install-v1

[`docs/contracts/production-install-v1.md`](docs/contracts/production-install-v1.md) is the single source of truth for when Tarka may claim a GitLab-grade / production install. This SUPPORT.md is G8 (commercial pack / severity intent). It is not the grade contract. Do not claim GitLab-grade from a green `helm template` of `prod-on-k8s`.

---

## Related

| Doc | Role |
|-----|------|
| [README](README.md) | Day-1 clone-and-run; tip honesty table |
| [CLAIM_LOCK](docs/compliance/CLAIM_LOCK.md) | Allowed language; must-not-ship |
| [production-install-v1](docs/contracts/production-install-v1.md) | Grade gates (G0–G8 + G9 checklist) |
| [product Day-1](docs/docs/guides/product-day1-install.md) | `make product` vs Helm skins |
| [pack GitOps](docs/docs/guides/pack-gitops.md) | Promote is live; git is export |
| [deployment](docs/docs/guides/deployment.md) | Helm `prod-on-k8s`, first-class OIDC |
| [LICENSE](LICENSE) | Elastic License 2.0 |
| [SECURITY](SECURITY.md) | Vulnerability reports (not a cert) |
