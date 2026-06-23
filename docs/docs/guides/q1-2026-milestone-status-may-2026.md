# Q1-2026 milestone status (May 2026 handoff)

**Date:** 2026-05-18 · **Decision:** Q1 umbrella issues **do not close in May**; evidence is linked for v1.2.0 where relevant. Capacity shifts to **75/25** trust/product per [tarka-12-month-roadmap-execution-kit.md](./tarka-12-month-roadmap-execution-kit.md) until v1.2.0 ships.

| Epic | Issue | May disposition | Evidence on `master` |
|------|-------|-----------------|----------------------|
| Q1-E01 Policy-as-code | [#127](https://github.com/pamu512/tarka/issues/127) | **Slip** to post–v1.2.0 | OPA under `infra/deploy/opa/`; no required `policy-check` PR gate |
| Q1-E02 Tenant binding | [#128](https://github.com/pamu512/tarka/issues/128) | **Slip** | `TENANT_BINDING_REQUIRED` env patterns; migration aids open |
| Q1-E03 Preset promotion | [#129](https://github.com/pamu512/tarka/issues/129) | **Slip** | Deploy presets exist; promotion framework partial |
| Q1-E04 SLO burn | [#130](https://github.com/pamu512/tarka/issues/130) | **Partial — not closed** | SLO HTTP + Prometheus burn rules ([service-slos-v1.md](./service-slos-v1.md)) |
| Q1-E05 Degraded UX | [#131](https://github.com/pamu512/tarka/issues/131) | **Partial — not closed** | Circuit breakers, `fallback_reason` ([v1.2.5 backlog](./v1.2.5-execution-backlog-status.md)) |
| Q1-E06 Release sign-off | [#132](https://github.com/pamu512/tarka/issues/132) | **Defer** to v1.3.0 | CI green path; governance checklist = June |
| Q1-E07 Env parity | [#133](https://github.com/pamu512/tarka/issues/133) | **In progress** | [`packages/deploy-settings`](../../../packages/deploy-settings) on `master` |
| Q1-E08 Runbooks | [#134](https://github.com/pamu512/tarka/issues/134) | **Slip** | Scattered runbooks; Epic C parity runbook added |

**GitHub comments:** use **Template A** in [github-epic-status-comments-may-2026.md](./github-epic-status-comments-may-2026.md) on each issue [#127](https://github.com/pamu512/tarka/issues/127)–[#134](https://github.com/pamu512/tarka/issues/134).
