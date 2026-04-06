# Saarthi Pro — roadmap (internal)

> **Maintainer detail:** Phases and dates are **not** contractual commitments. For a **buyer-facing** OSS vs commercial summary, use [Saarthi Pro vs OSS](saarthi-pro-vs-oss.md). This file tracks **engineering and GTM artifacts** tied to fraud-stack and the Saarthi-pro repo.

This roadmap ties **commercial deliverables** (Saarthi Pro repo, packaging, procurement artifacts) to **shared engineering** that ships first in the OSS reference (`services/investigation-agent` in **fraud-stack**). OSS-only technical backlog stays on [Investigation Agent Project](../projects/investigation-agent-project.md).

## Release and versioning discipline

- **Named Pro releases** (tags/changelog in [Saarthi-pro](https://github.com/pamu512/Saarthi-pro)) should declare the **integration contract** they ship: pin **`contract_version`** (from `GET /v1/integration`) and link [CHANGELOG_INTEGRATION](CHANGELOG_INTEGRATION.md).
- **Default rule:** Pro tracks the **same** `contract_version` lineage as the OSS agent at the pinned commit unless [Distribution & contract parity](saarthi-pro-distribution-and-contract-parity.md) documents an intentional fork (hotfix only, time-bounded).
- Buyers see **roadmap as phases**; engineering ships **incremental minors** with changelog entries.

## Phase 0 — Reference spine (shipped in fraud-stack)

| Theme | Outcome |
|-------|---------|
| Integration contract | `GET /v1/integration`, health block, `INTEGRATION_PROFILE_ID`, [investigation-agent-integration-contract.md](investigation-agent-integration-contract.md) |
| Conformance | Golden profile tests + CI matrix `test-investigation-agent-golden-matrix`; [adapter catalog & certification](saarthi-pro-adapter-catalog-and-certification.md) vocabulary |
| Adapter scaffolding | `templates/cookiecutter-saarthi-pro-adapter/` |
| Change process | [saarthi-customer-api-change-policy.md](saarthi-customer-api-change-policy.md) (MSA-overridable defaults) |
| Honest limits | [Assurance, warranties & liability positioning](saarthi-pro-assurance-liability-positioning.md) for sales/legal alignment |

## Phase 1 — Pro MVP (**playbooks delivered** in fraud-stack docs)

**Status:** Operational templates and checklists exist below. **Standalone image:** [`distributions/saarthi-pro-agent`](../../../distributions/saarthi-pro-agent/README.md) + [RELEASE.md](../../../distributions/saarthi-pro-agent/RELEASE.md). **Remaining execution:** publish to your registry under Saarthi Pro branding, optional separate Saarthi-pro git remote (submodule/vendor), and customer-specific certification sign-offs.

| Theme | Delivered artifact |
|-------|-------------------|
| Standalone distribution | [Standalone distribution layout](saarthi-pro-standalone-distribution-layout.md) (expected Saarthi-pro repo shape + build options) |
| Upgrade path | [Upgrade from OSS](saarthi-pro-upgrade-from-oss.md) |
| Parity narrative | [Distribution & contract parity](saarthi-pro-distribution-and-contract-parity.md) |
| Certification | [Certification checklist](saarthi-pro-certification-checklist.md) (Bronze / Silver / Sustained) |
| Support bundle | [Release notes template](saarthi-pro-release-notes-template.md) · [Support severity definitions](saarthi-pro-support-severity.md) |

## Phase 2 — Enterprise packaging (**playbooks delivered**)

**Status:** Architecture guides and procurement templates below are ready for counsel/customer success. **Remaining execution:** IdP-specific diagrams per deal, signed DPA, live subprocessor list.

| Theme | Delivered artifact |
|-------|-------------------|
| Identity | [SSO / SCIM integration guide](saarthi-pro-sso-scim-integration-guide.md) |
| Procurement | [DPA & subprocessor template](saarthi-pro-dpa-subprocessor-template.md) |
| Residency / VPC | [Residency & VPC deployment](saarthi-pro-residency-vpc-deployment.md) |
| Operations | [Managed operations runbook](saarthi-pro-managed-operations-runbook.md) |
| Connectors | [Adapter SOW template](saarthi-pro-adapter-sow-template.md) · populate rows in [adapter catalog](saarthi-pro-adapter-catalog-and-certification.md) |

## Phase 3 — Depth & differentiation (**specs + partial OSS implementation**)

**Status:** **Evidence bundle v1** fields and **optional analytics** hooks are implemented in `services/investigation-agent` (see [CHANGELOG_INTEGRATION](CHANGELOG_INTEGRATION.md)). **Remaining execution:** multi-tenant admin API, org-hosted analytics warehouse contracts, bundled inference SKUs, counsel-reviewed order-form exhibits.

| Theme | Delivered artifact |
|-------|-------------------|
| Evidence | [Evidence bundle v1 alignment spec](saarthi-pro-evidence-bundle-v1-alignment.md) |
| Analytics / admin | [Org analytics & multi-tenant admin spec](saarthi-pro-org-analytics-multitenant-spec.md) |
| Economics | [Economics & packaging appendix](saarthi-pro-economics-packaging-appendix.md) |
| Legal exhibits | [Legal & order-form addenda outline](saarthi-pro-legal-order-form-addenda-outline.md) |

## Phase 1–3 artifact index (quick links)

| Document |
|----------|
| [Standalone distribution layout](saarthi-pro-standalone-distribution-layout.md) |
| [Upgrade from OSS](saarthi-pro-upgrade-from-oss.md) |
| [Release notes template](saarthi-pro-release-notes-template.md) |
| [Support severity](saarthi-pro-support-severity.md) |
| [Certification checklist](saarthi-pro-certification-checklist.md) |
| [SSO / SCIM guide](saarthi-pro-sso-scim-integration-guide.md) |
| [DPA & subprocessor template](saarthi-pro-dpa-subprocessor-template.md) |
| [Residency & VPC](saarthi-pro-residency-vpc-deployment.md) |
| [Managed operations runbook](saarthi-pro-managed-operations-runbook.md) |
| [Adapter SOW template](saarthi-pro-adapter-sow-template.md) |
| [Evidence bundle v1 alignment](saarthi-pro-evidence-bundle-v1-alignment.md) |
| [Org analytics & multitenant spec](saarthi-pro-org-analytics-multitenant-spec.md) |
| [Economics appendix](saarthi-pro-economics-packaging-appendix.md) |
| [Legal order-form addenda outline](saarthi-pro-legal-order-form-addenda-outline.md) |

## Related

- [Adapter-first strategy & pricing](saarthi-pro-adapter-strategy-and-pricing.md)
- [Saarthi Pro vs OSS](saarthi-pro-vs-oss.md)
- [Investigation Agent Project](../projects/investigation-agent-project.md) (OSS gaps and OSS roadmap)
