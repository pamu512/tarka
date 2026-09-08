# Production install contract v1

Single source of truth for when Tarka may claim a **GitLab-grade / production install**.

Tarka application code is **source-available** under Elastic License 2.0 (not open-source). This file does **not** assert that the grade is already achieved. **Beta remains.** A `prod-on-k8s` preset existing is not GA and is not a GitLab-grade claim.

Beachhead for a CE-shaped VPC install: last-mile / food / q-comm / gig / retail. Not banks as P0.

See [CLAIM_LOCK](../compliance/CLAIM_LOCK.md). Rotation: [production-secrets-rotation](../docs/guides/production-secrets-rotation.md).

## Locks (do not smash)

- Evaluate stays Rust. The model never ALLOW / DENY / REVIEW / Promote / demote.
- Observe promote = gated-or-human. `shadow_auto_promote` default **off**.
- Empty plane URL = that plane off.
- Demo ≠ product compose ≠ sales-only overlay (`brochure` token).
- No sqlite / `emptyDir` for decisions, audit, labels, or packs in any preset labeled production.
- OIDC optional. API keys are the machine path. Empty `API_KEYS` + empty `OIDC_ISSUER` + insecure off = **fail closed** (503), not “no auth”. Missing secrets must not leave evaluate open.
- No Vault / External Secrets Operator as a hard dependency. Kubernetes Secret + `global.appSecretsName` is enough. Vault/ESO are optional operator tooling.
- No named fraud / risk product incumbents as reference points.

## Pass / fail — beachhead VPC CE-shaped

Applies when an operator labels a cluster **production** (`TARKA_DEPLOYMENT_PROFILE=production` and/or Helm `global.environment=prod` with the `prod-on-k8s` HA knobs).

| Gate | Pass | Fail |
|------|------|------|
| Data stores | External Postgres + Redis. In-cluster PG/Redis **off** on `prod-on-k8s`. Resolved `databaseUrl` / `redisUrl` (no `__PLACEHOLDER__`). | In-cluster PG/Redis; sqlite; `emptyDir` for decisions / audit / labels / packs; leftover `postgres.auth.password=fraud`. |
| Image pins | Production **publishes** pin `sha256:<64-hex>` on enabled images (`coreApi` / `signalApi` / `investigationAgent` as enabled). Tag is ignored when digest is set. | `:latest`. Mutable `1.3.0-beta` **without** digest on a grade-claiming apply. Empty digest is allowed only so CI `helm template` of placeholders still works — that is **not** a grade. G2 CI-enforces pins; this row is the claim rule. |
| Secrets | Operator-supplied keys in `global.appSecretsName`. No default passwords in prod examples. | Chart default `fraud`; `tarka-evidence-dev-secret`; committed real keys. |
| Auth | `API_KEYS` set (machine path). `allowInsecureNoAuth=false`. | Empty keys + empty OIDC + insecure off treated as open; `ALLOW_INSECURE_NO_AUTH=true`. |
| OIDC | Optional for desk humans. Empty issuer = local / API-key mode. Non-empty issuer requires resolved Redis (no in-process OIDC state fallback). | OIDC required to boot evaluate; issuer set without Redis. |
| Case / evidence | `CASE_API_PRODUCTION_MODE=true`. `EVIDENCE_SIGNING_SECRET` required (default HMAC refused). | sqlite fallback on Postgres bootstrap failure. |
| Evaluate | `TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=true`. | Production profile without idempotency. |
| Frontend / Shadow | `prod-on-k8s` keeps frontend **OFF** and Shadow **OFF**. | Treating that as a missing feature, or claiming the product desk from this chart. |
| Backup + upgrade | Backup drill docs ([G6](../docs/guides/production-backup-restore.md)) and upgrade docs (G7) exist and have been run on the named pilot. Redis is ephemeral. AGE Hunt is volume restore, not `pg_dump`. Not a hosted backup product. | Grade claim before G6/G7 land. Treating Redis dump or AGE `pg_dump` as SoR. |
| Grade | G0–G8 landed **and** G9 checklist on a **named** beachhead pilot. | Claiming GitLab-grade from this contract, from a green `helm template`, or from the preset existing. |

## Secrets matrix

Mount via `global.appSecretsName`. Do not put values in Helm values, compose examples, or this file.

| Key | Production | Notes |
|-----|------------|-------|
| `API_KEYS` | **Required** | Machine path. Empty + empty `OIDC_ISSUER` + insecure off → 503. |
| `EVIDENCE_SIGNING_SECRET` | **Required** | `CASE_API_PRODUCTION_MODE` refuses the default HMAC. |
| `RULE_GOVERNANCE_SECRET` | Required on **enterprise-desk** | Two-person live-rule. Optional on evaluate-only `prod-on-k8s`. |
| Buyer Postgres URL | **Required** on `prod-on-k8s` / enterprise-desk | `global.externalServices.postgres.databaseUrl` (operator-supplied). In-cluster PG **off**. Never document `fraud` as a prod password. |
| Buyer Redis URL | **Required** on `prod-on-k8s` / enterprise-desk | `global.externalServices.redis.redisUrl`. In-cluster Redis **off**. Required when `OIDC_ISSUER` is set (no in-process OIDC state). |
| `coreApi.oidc.{issuer,audience,jwksUrl,rolesClaim}` | Optional | Desk humans. Helm values SoT (not extraEnv). Empty issuer = API-key mode. |
| `OIDC_CLIENT_SECRET` | If issuer set | Desk humans only. Not a substitute for `API_KEYS`. |
| `ATTESTATION_HMAC_SECRET` | If attestation on | Empty = that plane off. |
| `OPENAI_API_KEY` / `UPSTREAM_API_KEY` | If Advise / investigation LLM on | Chart Shadow stays **OFF**. Investigation-agent on `prod-on-k8s` also needs `COPILOT_PRODUCTION_MODE` (no `ALLOWED_ANALYSTS=*`). |
| `POSTGRES_PASSWORD` | Do not use in-cluster PG | External URL carries buyer credentials. Never document `fraud` as a prod password. |
| `AGE_POSTGRES_PASSWORD` | Required on **enterprise-desk** | Hunt sidecar. `secretKeyRef`, not chart default `fraud`. |
| `AGE_DATABASE_URL` | Required on **enterprise-desk** | Graph-service AGE URL via `secretKeyRef`. |

`TARKA_DEPLOYMENT_PROFILE=production` runs the same fail-closed checks as Helm prod. Setting individual knobs without the profile leaves those checks off.

## Auth

| Actor | Path | Required for grade? |
|-------|------|---------------------|
| Machines / evaluate | `API_KEYS` (`X-API-Key`) | Yes |
| Desk humans | OIDC optional (`coreApi.oidc.{issuer,audience,jwksUrl,rolesClaim}`; secret key `OIDC_CLIENT_SECRET`) | No. Empty issuer stays valid. |

Empty keys + empty OIDC + insecure off = fail closed. Missing secrets must not leave evaluate open. `coreApi.oidc.*` is the first-class Helm values SoT.

## Frontend / Shadow on `prod-on-k8s`

Frontend **OFF** and Shadow **OFF** on the prod chart are **intentional grade policy**, not a missing feature.

- Evaluate HA is the CE-shaped beachhead (replicaCount 2, tenant binding on, investigation-agent ON with `dataPersistence.mode=postgres`).
- Hunt glass / product desk is `make product` (compose) or `enterprise-desk-on-k8s` (still beta, still not the grade).
- No Tarka-branded model. Operator BYO URL later.

## Grade claim (G0–G8 + G9)

Claim **GitLab-grade** only after the locked 2026-09-08 plan items **G0–G8** land **and** a **named** beachhead pilot passes the **G9** checklist.

| Id | Gate | Landed |
|----|------|--------|
| G0 | This contract | yes |
| G1 | Helm prod honesty CI (`helm_prod_honesty.sh`) | yes |
| G2 | Digest-pin CI (`--digest-map` + `helm_prod_digest_honesty.py`) | yes |
| G3 | Secrets matrix + rotation ([production-secrets-rotation](../docs/guides/production-secrets-rotation.md)) | yes |
| G4 | SSO (OIDC for desk humans; API keys stay the machine path) | yes |
| G5 | NetworkPolicy + ServiceMonitor default-on (`prod-on-k8s`) | yes |
| G6 | Backup drill docs ([production-backup-restore](../docs/guides/production-backup-restore.md)) | yes |
| G7 | Upgrade docs ([production-upgrade](../docs/guides/production-upgrade.md)) | yes |
| G8 | Commercial SUPPORT.md | yes |
| G9 | Named-pilot checklist ([soak](../docs/guides/production-install-soak-checklist.md)) | **this PR** (sheet exists; unsigned) |

G0–G8 docs/CI are on tip. G9 is the named-pilot sign-off. Do not treat a green `helm template` of `prod-on-k8s` as the grade.

## What each skin may claim

| Skin | May claim | Must not claim |
|------|-----------|----------------|
| **lite** compose | Day-1 evaluate + AGE Hunt on a laptop / VM. In-cluster PG/Redis and `ALLOW_INSECURE_NO_AUTH` are local defaults. | Production install. GitLab-grade. GA. |
| **demo** (`make demo`) | First-hour pages. No `shadow_agent`. | Product desk. Production. GitLab-grade. |
| **product** compose (`make product`) | Analyst jobs + `desk_provision.json` on compose. `shadow_agent` only when an LLM URL is set. | Helm `prod-on-k8s`. GitLab-grade. GA. |
| **prod-on-k8s** | core-api HA overlay **exists** (external PG/Redis required; frontend / Shadow OFF). Beta image tags until digest-pinned. | GA. GitLab-grade (until G0–G8 + G9). Product desk. In-cluster PG/Redis as production. sqlite / `emptyDir` for decisions / audit / labels / packs. |
| **enterprise-desk** | Thin desk + Hunt sidecar on buyer SoR Postgres + Redis. Still beta. | GitLab-grade. GA. Hosted Tarka Cloud. |

Sales-only overlay (`VITE_DESK_PROFILE=brochure`) is pitch pages. Not a production skin.

## Out of scope

- SOC 2 / PCI from fixture CI (mapping suite is not a cert)
- Hosted Tarka Cloud / providing Tarka to third parties as a managed service
- Case CRM
- Consortium SKU
- Implementing G2–G9 in this PR (G1 is the Helm honesty CI gate; not the grade)
- Vault operator required
- Claiming GitLab-grade already achieved
