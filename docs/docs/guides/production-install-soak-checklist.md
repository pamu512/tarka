# Production install soak checklist (G9)

Named-pilot sign-off for a **GitLab-grade / production install** claim. This page is the soak gate. It is **not** the grade.

Tarka application code is **source-available** under Elastic License 2.0 (**ELv2**, not open-source). **Beta remains.** There is no GA tag. There is **no SOC 2** (or PCI) from this file, from fixture CI, or from [`docs/compliance/soc2-pci/`](../../compliance/soc2-pci/). Beachhead is CE-shaped VPC evaluate-HA on last-mile / food / q-comm / gig / retail — **not banks** as P0. Do not name peer fraud / risk products.

**Claim lock:** “GitLab-grade install” is allowed **only** when **G0–G8 have landed** on the tip you apply **and** this checklist is **signed** for a **named** pilot (internal or buyer). A green `helm template` of `prod-on-k8s`, this file existing, or `prod-on-k8s` existing is **not** the grade. See [CLAIM_LOCK](../../compliance/CLAIM_LOCK.md).

This soak is **install-side**. It is **not** “primary decisioner” maturity (pack quality, live-tenant holdout, or product-wide scores). Do not smash those claims.

## Locks

- Evaluate stays Rust. The model never ALLOW / DENY / REVIEW / Promote / demote.
- Default `enforcement.mode` is `emit_only` ([enforcement-v1](../../contracts/enforcement-v1.md)). Handoff is never Day-1.
- Empty plane URL = that plane off.
- No sqlite / `emptyDir` for decisions, audit, labels, or packs on a production-labeled apply.
- No named fraud / risk product incumbents as a reference.

## Related (G0–G8 landed on tip)

Docs below are on this tip. A row still stays **fail** until the *pilot* work is dated — landing the file is not a pass.

| Doc | Role |
|-----|------|
| [production-install-v1](../../contracts/production-install-v1.md) | G0 contract — when a grade *may* be claimed. Not the grade. |
| [SUPPORT.md](../../../SUPPORT.md) | G8 commercial pack + community (no SLA). Not the grade. |
| [deployment.md](deployment.md) | Helm catalog, `prod-on-k8s`, digest + NetworkPolicy |
| [production-secrets-rotation.md](production-secrets-rotation.md) | G3 rotate `API_KEYS` / signing secrets |
| [production-backup-restore.md](production-backup-restore.md) | G6 SoR Postgres drill |
| [production-upgrade.md](production-upgrade.md) | G7 digest-to-digest dry-run + practiced rollback |
| [service-slos-v1.md](service-slos-v1.md) | Aspirational / buyer-owned SLO *targets*. Not a Tarka nines SLA. |

## Named pilot

Fill this block **before** any row can count as a grade sign-off. Internal lab and paid beachhead buyer are both valid. Do not invent users, LOI volume, or ARR.

| Field | Value |
|-------|-------|
| Pilot name (internal **or** buyer) | ________ |
| Preset / cluster | `prod-on-k8s` / other: ________ |
| Operator / owner | ________ |
| Soak start (UTC) | ________ |
| Sign-off (UTC) | ________ |
| Signer | ________ |

Unsigned / unnamed = **not** a GitLab-grade claim.

## Pass / fail

Every row needs **pass** or **fail**, a **date**, and an **owner**. Blank date or owner = fail. One fail = the sheet is not signed.

| # | Item | Pass / fail | Date (UTC) | Owner |
|---|------|-------------|------------|-------|
| 1 | Digests pinned on prod values | ________ | ________ | ________ |
| 2 | Secrets rotated once | ________ | ________ | ________ |
| 3 | OIDC or API-key path proven | ________ | ________ | ________ |
| 4 | Backup drill dated (G6) | ________ | ________ | ________ |
| 5 | Upgrade dry-run dated (G7) | ________ | ________ | ________ |
| 6 | NetworkPolicy on | ________ | ________ | ________ |
| 7 | Evaluate SLOs on buyer TPS (placeholder metrics) | ________ | ________ | ________ |
| 8 | ≥2 weeks Observe before handoff / enforcement mode | ________ | ________ | ________ |

### 1 — Digests pinned on prod values

**Pass:** The values **applied** to this pilot pin `sha256:<64-hex>` on every enabled image (`coreApi`, and `signalApi` / `investigationAgent` when those workloads are on). Tag is ignored when digest is set. Mutable `1.3.0-beta` without digest is **fail**. Empty digest is allowed only so CI `helm template` of placeholders still works — that apply is **not** this row.

How: [deployment.md](deployment.md) (`coreApi.digest`). G2: `generate_cloud_values.py --digest-map` is required on the `prod-on-k8s` publish helper.

### 2 — Secrets rotated once

**Pass:** After first apply, `API_KEYS` and required signing secrets (`EVIDENCE_SIGNING_SECRET`, plus `OIDC_CLIENT_SECRET` / `RULE_GOVERNANCE_SECRET` if those planes are on) were rotated **once** on this pilot and evaluate still fail-closes when keys are empty. Chart default `fraud` / `tarka-evidence-dev-secret` as the live secret is **fail**.

How: Kubernetes Secret named by `global.appSecretsName`. Runbook: [production-secrets-rotation.md](production-secrets-rotation.md). Vault / ESO optional, not required.

### 3 — OIDC or API-key path proven

**Pass:** At least one path works on this pilot:

| Path | Proof |
|------|--------|
| **API keys** (machines / evaluate) | `X-API-Key` evaluate returns 200 + pack-why. Empty keys + empty issuer + insecure off = **503**, not open. |
| **OIDC** (desk humans, optional) | Non-empty issuer: desk `GET /auth/config` → `oidc_enabled: true`, login works, Redis resolved (no in-process OIDC state fallback). |

Either path is enough. Both empty + insecure off is **fail**. OIDC is not required to boot evaluate. G4 SoT is first-class Helm `coreApi.oidc.{issuer,audience,jwksUrl,rolesClaim}` ([deployment.md](deployment.md)). ExtraEnv `OIDC_*` is leftover fallback only.

### 4 — Backup drill dated (G6)

**Pass:** Dated run of the G6 SoR drill (decisions + audit + packs + labels on **external** Postgres). Redis is ephemeral velocity — an empty Redis after restore is expected. AGE Hunt on `enterprise-desk` is a **volume** restore, not `pg_dump`.

How: [production-backup-restore.md](production-backup-restore.md). Undated buyer snapshot lore is **fail**.

### 5 — Upgrade dry-run dated (G7)

**Pass:** Dated digest-to-digest (or recorded Helm revision) dry-run on this single-cluster beachhead: preflight, `helm upgrade` **or** `helm template` of the to-pin, verify evaluate, practiced rollback. Expand/contract only. Not multi-region.

How: [production-upgrade.md](production-upgrade.md). Undated dry-run is **fail**.

### 6 — NetworkPolicy on

**Pass:** The running `prod-on-k8s` (or `global.environment=prod`) apply emits default-deny NetworkPolicy plus the chart allow rules (kube-dns, same-namespace, evaluate ingress). `kubectl -n <ns> get networkpolicy` shows them. Opt-out (`global.networkPolicy.enabled=false`) is **fail** for this row.

How: [deployment.md](deployment.md). G5: `prod-on-k8s` sets `global.networkPolicy.enabled: true`. Lite / default values emitting none is correct and is **not** this pilot.

### 7 — Evaluate SLOs on buyer TPS (placeholder metrics)

**Pass:** This pilot wrote **buyer** numbers — not Tarka nines as an SLA. Fill the placeholders. [service-slos-v1](service-slos-v1.md) targets are aspirational / buyer-owned. [SUPPORT.md](../../../SUPPORT.md) community track has **no** availability percentage.

| Placeholder | Buyer value | How measured |
|-------------|-------------|--------------|
| Target evaluate TPS (this pilot) | ________ | Load gen / real traffic, not README laptop figures |
| p95 evaluate latency (ms) vs target | ________ / ________ | `GET /decisions/v1/slo` or Prometheus `/metrics` |
| 5xx ratio (5m / 1h) vs budget | ________ / ________ | [slo-burn-response](../operations/slo-burn-response.md) |
| Error-budget window (days) | ________ | Buyer policy, not a Tarka cert |

Blank TPS = **fail**. Citing a Tarka 99.99% (or any nines) SLA = **fail**.

### 8 — ≥2 weeks Observe before handoff / enforcement mode

**Pass:** This named pilot ran **≥14 days** in Observe / `emit_only` (pack canary + observe-only evaluate) **before** any `enforcement.mode=handoff`. Soak start and sign-off dates above must span 14 days. Handoff is buyer-contracted, never the compose or `prod-on-k8s` default.

`GET /decisions/v1/ops/enforcement-mode` (or equivalent on the tip you run) stays `emit_only` for the window. Auto-Promote stays **off** unless tenant promote gates are explicit and already met.

Shorter soak, or handoff on Day-1, is **fail**.

## Sign-off

Copy this block only when **every** row is **pass** and the named-pilot fields are filled.

```
Pilot: ________
G0–G8 on applied tip: yes / no
All 8 rows pass: yes / no
GitLab-grade install claim for this pilot only: yes / no
Primary decisioner claim: no
SOC 2 / GA / hosted Tarka Cloud: no
Signer / date (UTC): ________
```

A “yes” on the grade line applies to **this named pilot** only. It does not promote the product to GA and does not make Tarka a primary decisioner.

## Out of scope

- Claiming GitLab-grade complete by landing this file or this PR
- Primary decisioner / product-wide maturity scores
- SOC 2 / PCI from fixture CI or this checklist
- Hosted Tarka Cloud / providing Tarka as a managed service
- Banks as P0; users / LOI / ARR as traction
- Inventing a Desktop “production-readiness” file that is not in this repo
