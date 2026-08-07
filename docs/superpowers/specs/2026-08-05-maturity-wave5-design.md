# Maturity Wave 5 Design (evidence → 4.0 path)

**Date:** 2026-08-05  
**Status:** Approved  
**Branch:** `maturity-4-0-local`  
**Prior:** [2026-08-05-maturity-4-0-hybrid-design.md](./2026-08-05-maturity-4-0-hybrid-design.md)

## Goal

Close evidence gates so competitive scores stop overclaiming, then ship the smallest ops slice that can honestly move Fraud Ops / Analyst toward **4.0–4.2**.

## Approach

Hybrid **C**: 5a evidence first, then smallest 5b product slice.

## Non-goals

- Native Incognia-class co-presence
- Full `mockData.ts` deletion
- Claiming matrix ≥4.0 until acceptance gates pass

## 5a — Evidence

1. Live/offline golden loop hardened; offline always in CI
2. Partner fusion fixture smoke (no live vendor keys)
3. Honest matrix rewrite (hybrid column = regrade; 4.0–4.2 = target)

## 5b — Product slice

4. Counter replay job surface → JSON artifact under `artifacts/`
5. Prod desk mock gate script (CI)
6. Desk QA path smoke over existing case-api ops routes / pure helpers

## Acceptance

| Gate | Pass criteria |
|------|----------------|
| Stubs | `audit_stubs.py` OK |
| Golden | offline OK; live when `DECISION_API_URL` set (exit 1 on fail); `REQUIRE_DECISION_API=1` forces live |
| Fusion | fixture smoke exit 0 |
| Matrix | hybrid column matches honest regrade, not aspirational 4.05 |
| Counter job | writes `artifacts/counter-replay-job.json` with pass/fail |
| Mock gate | `audit_prod_desk_mocks.py` OK |
| QA | desk smoke exit 0 |

## Out of scope (later)

Per-rule telemetry depth, skills-based routing, live partner tenant proof.
