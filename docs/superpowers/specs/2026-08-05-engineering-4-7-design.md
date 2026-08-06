# Engineering ≥4.7 — surgical honesty stack

**Date:** 2026-08-05  
**Branch:** `maturity-4-0-local`  
**Status:** Approved design (Approach 1)  
**Bar:** Critical / skeptical — score moves only with durable CI + lean-build evidence

## Goal

Move the **Engineering** end-user lens from ~**3.8** to **≥4.7** under the same critical regrade rules that rejected liberal 4.2 claims. Risk/Strategy and Fraud Ops are **not** in scope for this score bump unless separately earned.

## Problem (what holds Engineering at ~3.8)

| Flag | Gap | Evidence today |
| ---- | --- | -------------- |
| #6 | QA desk e2e unproven as merge gate | `ops-qa-desk-e2e.yml` weekly/dispatch only |
| #7 | Brochure mock surface still huge | ~4768 lines `frontend/src/api/mockData*.ts` |
| — | Desk pages still import god `client.ts` | Lean pages mixed `api/v1/*` vs `../api/client` |
| — | Contract proof uneven | MC HTTP + y_label store tests exist; not called out as eng gate |

Already solid (keep): `VITE_DESK_STRICT`, `deskMockPolicy`, `audit_prod_desk_mocks.py`, stub AST gate, lean nav desk-core, durable y_label + proxy-off bins.

## Approach

**Surgical honesty stack** — harden existing gates; do **not** delete all mocks or break demo builds.

1. Isolate mockData from lean/prod desk paths  
2. PR-gate QA desk Playwright with artifacts  
3. Expand honesty / import audits  
4. Typed desk API surface (`api/v1/*`) for lean core pages  
5. Service contract smokes required on PR CI  
6. Regrade canvas/matrix only after green evidence  

## Non-goals

- Full `mockData*.ts` deletion  
- Offline sales brochure demotion beyond lean/demo split  
- Live partner enrichment proof (Risk lens)  
- Sift-class queue OR / shadow-vs-primary ops UI (Fraud Ops)  
- Claiming overall product 4.2 or six-cap mean 4.2  

## Design

### 1. MockData isolation (flag #7)

**Intent:** Mocks may remain in the repo for `VITE_LEAN_NAV=false` demo builds, but must not be loadable on lean desk API paths.

**Mechanics:**

- Lean/prod default (`LEAN_NAV` on, `VITE_DESK_STRICT` on): `request()` must not fall back to `getMockResponse` for desk API paths (already true when mocks not forced).  
- Strengthen so lean desk code paths do not **statically** or **eagerly** pull brochure `mockData*` into the desk chunk (dynamic import only behind demo/mock-forced branches, or Vite conditional).  
- Expand `scripts/audit_prod_desk_mocks.py` (and/or new `scripts/audit_lean_desk_imports.py`):  
  - Fail if `frontend/src/api/v1/*` imports `mockData`  
  - Fail if lean desk pages import `mockData`  
  - Keep existing production `VITE_USE_API_MOCKS=true` forbid  

**Success:** Audit green; lean production build does not serve desk routes from brochure mocks.

### 2. PR-gated QA desk e2e (flag #6)

**Intent:** Merge-blocking proof that `/ops/qa` works mock-free.

**Mechanics:**

- Reuse `frontend/e2e/ops-qa-desk.spec.ts` (`E2E_QA_DESK=1`).  
- Add a **pull_request** (+ `main`) job — prefer `workflow_call` from `ops-qa-desk-e2e.yml` or a slim twin in `ci.yml`.  
- Boot micro profile via existing reset/e2e scripts; upload Playwright report on failure (success summary optional).  
- Keep weekly schedule as soak; PR job is the honesty gate.  

**Success:** Required check exists; at least one green run on this branch with artifact path documented.

### 3. Honesty gate expansion

**Intent:** Regressions that re-enable desk mocks or widen lean nav fail CI before merge.

**Mechanics:**

- Extend prod-desk mock audit as in §1.  
- Assert lean nav desk-core invariants still hold (simulation/shadow/admin out of `LEAN_NAV_PATHS`).  
- Optional self-check fixture proving the audit fails on a synthetic bad import.  
- Remain in the existing `ci.yml` honesty job cluster.  

**Success:** Gate fails loud on a known-bad pattern; green on trunk.

### 4. Typed desk API surface

**Intent:** Lean desk pages talk cases/decisions/disputes through versioned modules, not the god barrel, so mock shrinkage and contract scope stay enforceable.

**Mechanics:**

- Migrate lean desk pages that still import cases/decisions from `../api/client` → `api/v1/cases` / `api/v1/decisions` / `api/v1/disputes`.  
- Ensure `joinDispositionLabels` / `dispatchChallenge` are reachable from the decisions v1 surface (re-export or move).  
- Import audit covers those pages.  

**In-scope pages (minimum):** `Cases`, `CaseDetail`, `OpsQaDesk`, `OpsCalibration`, `Disputes` (+ already-migrated SAR/workload pages stay on v1).

**Success:** Lean core desk pages use v1 modules for case/decision/dispute ops; audit enforces no `mockData` imports there.

### 5. Service contract smokes (PR CI)

**Intent:** Backend eng contracts that unlocked flag-fix stay merge-blocking.

**Mechanics (prefer reuse over new scripts):**

- `test-case-api`: includes `tests/test_maker_checker_http.py` (+ unit disposition tests).  
- `test-decision-api`: includes y_label store persist, `ReliabilityBinsBody` proxy-off default, challenge dispatch behavior (503 unconfigured / success when webhook mocked).  
- If those jobs are already required on PR, document them as the Engineering contract gate.  
- Only add `scripts/oss/eng_contract_smoke.py` if pytest jobs are not on the same required path.  

**Success:** Named tests green and required for merge.

### 6. Regrade evidence

**After** §1–§5 green:

- Update `docs/superpowers/canvases/maturity-4-0-regrade.canvas.tsx` and Cursor canvas copy: Engineering **≥4.7**.  
- Update `docs/docs/guides/competitive-score-matrix-2026-04.md` footnotes.  
- List job names / audit scripts as evidence.  
- Do **not** inflate Risk/Ops or overall to 4.2.

## Acceptance (skeptical checklist)

Engineering may be scored **≥4.7** only if **all** are true:

1. Lean/prod desk mock isolation audit green in PR CI  
2. QA desk Playwright PR job green at least once with report/artifact path  
3. Honesty gate expansion green (and bites on synthetic bad import if self-check added)  
4. Lean desk core pages on `api/v1/*` for cases/decisions/disputes  
5. Case-api MC HTTP + decision-api label/proxy/challenge contract tests green in PR CI  
6. Regrade canvas/matrix updated **after** the above, not before  

## Risks

| Risk | Mitigation |
| ---- | ---------- |
| Playwright PR job flaky / slow | Slim spec; micro profile; timeout budget; weekly soak remains |
| Demo break when mocks tree-shaken | Keep mocks for `VITE_LEAN_NAV=false` only |
| Import migration churn in CaseDetail | Re-export from v1; surgical page import edits |
| Score inflation without green CI | Acceptance forbids canvas bump until gates pass |

## Evidence map (target)

| Claim | Proof artifact |
| ----- | -------------- |
| Desk mocks forbidden in prod/lean | `audit_prod_desk_mocks.py` (+ lean import audit) in `ci.yml` |
| QA desk mock-free | PR Playwright job + `ops-qa-desk.spec.ts` |
| MC distinct actors | `test_maker_checker_http.py` in `test-case-api` |
| Durable labels / proxy-off | `test_label_join_and_kill_criteria.py` in `test-decision-api` |
| Typed desk surface | v1 imports + import audit |

## Open questions (resolved in brainstorm)

- Earn vs claim: **Earn** (critical bar)  
- Scope: mockData + PR e2e + typed surface + honesty gates + contract smokes (**all**)  
- Approach: **Surgical honesty stack** (not big-bang mock delete)
