# Missed-Mark Bridge Design

**Date:** 2026-08-05  
**Status:** Bridge Tracks A–D complete (narrative closed)  
**Source:** [end-user product review](../../../../.cursor/projects/Users-pamu-Documents-GitHub-tarka/canvases/end-user-product-review.canvas.tsx) “Missed the mark” + residual gaps after Waves 0–6  
**Branch:** `maturity-4-0-local`

## Goal

Close the **residual** missed-mark findings so Engineering, Risk/Strategy, and Fraud Ops no longer fail the original diligence critique — without pretending to own Incognia/Sift network effects or vendor SOC2.

## Already closed (do not re-build)

| Missed mark | Status |
|-------------|--------|
| README hypothetical TPS as front-door metric | Moved to benchmarks README |
| Honesty Tracks A–F checklist + stub CI | Gated; verify before claiming |
| Partner enrichment posture (hybrid) | Fusion + tenant proof + SHA pin |
| Calibration proxy-as-truth (partial) | `y_label` join + refuse healthy on proxy-only |
| Typology kill criteria | Vertical packs + promote_gate |
| Production `metadata.shadow` | Evaluate non-mutating path |
| Ops QA sampling product | `/ops/qa` + case-api ops routes |
| SAR transport Potemkin (Track D claim) | Worker + fail-closed when SFTP unset — **re-verify E2E** |

## Residual gaps (bridge scope) — Track D disposition

| # | Missed mark | Disposition | Evidence |
|---|-------------|-------------|----------|
| 1 | Brochure desk / DEV mock fallback | **Closed** | `VITE_DESK_STRICT` + `deskMockPolicy` + `audit_prod_desk_mocks` |
| 2 | No fraud-desk profile | **Closed** | `docker-compose.fraud-desk.yml` + README Start here |
| 3 | Hardware triad as happy path | **Closed** | Lite-first + fraud-desk front door |
| 4 | Live tenant partner proof | **Waiver** | Fixture pin `3d1ab910…`; live opt-in or `WAIVED` line in PR/runbook |
| 5 | Challenge / step-up layer | **Closed** | `challenge_orchestrator` + `decision-to-customer-journey.md` |
| 6 | Disposition → `y_label` | **Closed** | Reason-code enum + join + maker-checker |
| 7 | Demo > production truth | **Closed** | Lean nav default + desk-strict |
| 8 | Queue economics | **Closed** | SLA-by-priority + `CASE_MAKER_CHECKER_STATUSES` |
| 9 | Rule FP after labels | **Closed** | `rule-precision-after-labels` + Rule performance panel |
| 10 | SAR honesty E2E | **Closed** | SAR smoke CI + `.github/workflows/ops-qa-desk-e2e.yml` |

Regrade artifact: canvas `maturity-4-0-regrade.canvas.tsx`.

## Explicit non-goals

- Native global device reputation / Incognia co-presence physics  
- Tarka-as-vendor SOC2 Type II  
- Matching Sift queue OR as a multi-year ops-research product in one quarter

## Success criteria

A missed mark is **bridged** when: (a) production path does not depend on mocks, (b) one runnable proof/CI gate exists, (c) lean Day-1 docs lead with that path, (d) regrade notes the finding as closed with evidence SHA/path.
