# Missed-Mark Bridge Implementation Plan

> **Status:** Tracks A–D complete (narrative closed)  
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bridge residual “missed the mark” findings from the end-user review so Day-1 desk, strategy loop, and ops economics are honest and productized — without native vendor-network claims.

**Architecture:** Four sequential tracks (Truth → Desk loop → Actions → Install). Each track ends with a CI/smoke gate and a one-line evidence pointer in the competitive/honesty docs. Prefer delete/degrade over new platforms.

**Tech Stack:** existing FastAPI services, Vite SPA (`frontend/`), Playwright e2e, GitHub Actions, Redis/Postgres already in lite/micro compose.

**Spec:** `docs/superpowers/specs/2026-08-05-missed-mark-bridge-design.md`

## Global Constraints

- No silent stubs; Prefer **501 / 503 + reason_code** over fake KPIs  
- Hybrid device/location only (partner fusion); no native reputation network  
- Lean nav stays default; demo surfaces stay behind `VITE_LEAN_NAV=false`  
- TDD for new logic; every track leaves one smoke/CI check  
- Touch fewest files; reuse `partner_fusion_tenant_proof`, QA desk, calibration posture

## File map

| Path | Role |
|------|------|
| `frontend/src/api/client.ts`, `mockData*.ts` | Kill DEV auto-mock on desk paths; shrink case/calibration mocks |
| `frontend/src/pages/Cases.tsx`, `CaseDetail.tsx`, `OpsQaDesk.tsx` | Golden analyst loop + reason codes → label join |
| `frontend/e2e/ops-qa-desk.spec.ts`, new `golden-analyst-loop.spec.ts` | Mock-free desk proof (`E2E_QA_DESK=1`) |
| `services/decision-api/.../challenge*` / webhooks | Executable step-up path from `recommended_action` |
| `services/case-api/...` | Maker-checker on high-impact dispositions; SLA queue clocks |
| `services/decision-api/.../rule_api` / analytics | Post-label rule FP dashboard API |
| `infra/deploy/docker-compose.fraud-desk.yml` (new) | One opinionated Day-1 profile |
| `docs/docs/guides/oss-15-minute-first-decision.md`, README | Lite-first install story |
| `scripts/oss/sar_transport_honesty_smoke.py` (new) | SAR worker honesty gate |
| `docs/compliance/...` | Evidence pointers per closed miss |

---

## Track A — Production truth (Engineering misses)

### Task A1: Desk paths refuse mock fallback when `VITE_DESK_STRICT=1` ✅

- [x] `deskMockPolicy.ts` + vitest; `client.ts` uses `allowMocksForRequest`  
- [x] Default ON; only `VITE_USE_API_MOCKS=true` allows desk mocks  

### Task A2: Shrink case/calibration mock surface ✅

- [x] Ops/QA/kpis/cohort/playbooks/views moved to `mockData.cases.ts`  

### Task A3: SAR honesty smoke ✅

- [x] `scripts/oss/sar_transport_honesty_smoke.py` + CI  

### Task A4: Fraud-desk compose profile + README front door ✅

- [x] `docker-compose.fraud-desk.yml` overlay + README Start here + 15-min guide

---

## Track B — Strategy loop (Risk misses)

### Task B1: Live partner proof as release checklist item ✅

- [x] PR template checkbox + existing runbook  

### Task B2: Disposition → `y_label` closed loop from CaseDetail ✅

- [x] `decisions.joinDispositionLabels` + CaseDetail terminal status join toast  
- [x] Reason-code enum enforcement (`dispositionReasonCodes` + case-api `disposition.py`)  

### Task B3: Challenge action layer (minimum executable) ✅

- [x] Existing `challenge_orchestrator` + unit tests + journey guide

---

## Track C — Ops economics (Fraud Ops misses)

### Task C1: Maker-checker default on high-impact dispositions

**Files:** `services/case-api/...`, `CaseDetail.tsx`

- [x] Config: `CASE_MAKER_CHECKER_STATUSES=resolved_fraud,sar_filed,...`  
- [x] Second distinct actor required before commit; audit both  
- [x] UI: request review / approve review states  
- [x] Tests for same-actor rejection  

### Task C2: Per-queue SLA clocks

**Files:** case-api ops KPIs, `Cases.tsx`

- [x] Expose SLA breach counts **by queue/priority** (not only global)  
- [x] Cases queue header shows clock for active filter  

### Task C3: Rule performance after my labels

**Files:** decision-api rule analytics or new thin endpoint, `RulePerformance.tsx`

- [x] API: precision/FP proxy using `y_label` joined rows per `rule_id` (windowed)  
- [x] UI panel: “After dispositions (N labels)” with empty-state when coverage low  
- [x] Refuse green “healthy” styling when coverage &lt; threshold (reuse posture helpers)  

### Task C4: Enable mock-free QA e2e in CI micro profile

**Files:** `frontend/e2e/ops-qa-desk.spec.ts`, `docker-compose.micro.e2e.yml` / CI job

- [x] Wire `E2E_QA_DESK=1` on existing micro e2e job if present; else document manual gate  
- [x] Golden path: sample → pending → agree/disagree → metrics  

---

## Track D — Close the narrative

### Task D1: Regrade + matrix honesty pass

**Files:** regrade canvas, `competitive-score-matrix-2026-04.md` footnotes

- [x] Mark each original missed mark Closed / Partial / Won’t with evidence path  
- [x] Downgrade any 4.2 claim that still lacks Track A–C gates *(none — A–C complete; no inflation; 2 Partials documented)*  

### Task D2: One golden analyst path doc

**Files:** new or update `docs/docs/guides/golden-analyst-loop.md`

- [x] Queue → CaseDetail (graph+rules+shadow) → reason-coded disposition → QA sample → calibration  
- [x] Link fraud-desk compose + partner proof + QA e2e  

---

## Suggested sequence (calendar)

| Week | Track | Outcome |
|------|-------|---------|
| 1 | A1–A4 | Strict desk, SAR smoke, fraud-desk compose, README front door |
| 2 | B2–B3, B1 | Label loop + challenge webhook + live-proof checklist |
| 3 | C1–C3 | Maker-checker, SLA by queue, rule FP after labels |
| 4 | C4, D1–D2 | E2E QA in CI, regrade, golden analyst guide |

## Verify (full bridge)

```bash
python3 scripts/audit_stubs.py
python3 scripts/audit_prod_desk_mocks.py
python3 scripts/oss/partner_fusion_tenant_proof.py --mode fixture
python3 scripts/oss/sar_transport_honesty_smoke.py   # after A3
# frontend vitest for desk strict
# E2E_QA_DESK=1 playwright ops-qa-desk (after C4)
```

## Out of bridge (park)

- Native co-presence / global device graph  
- Full mockData deletion (strict desk + shrink is enough)  
- Sift-class skills-based routing OR engine  

---

## Execution handoff

After approval, run **Track A first** (unblocks trust). Do not start Track C UI until A1 strict mode lands — otherwise e2e teaches mocks again.
