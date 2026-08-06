# Fraud Ops 4.2–4.4 — desk ops triad

**Date:** 2026-08-05  
**Branch:** `maturity-4-0-local`  
**Status:** Approved design (Approach 1)  
**Bar:** Critical / skeptical — score moves only with durable desk + CI evidence

## Goal

Move the **Fraud Ops** end-user lens from ~**3.7** to **4.2–4.4** under the same critical regrade rules used for Engineering 4.7. Engineering stays **4.7**. Risk/Strategy stays ~**3.6** unless separately earned. Do **not** claim product-wide 4.2.

## Problem (what holds Fraud Ops at ~3.7)

| Gap | Today | Needed |
| --- | ----- | ------ |
| Challenge | Desk can call dispatch; unset webhook → 503 only | Configured sink + delivery proof in UI/tests |
| FP support | Clipboard “support-safe summary” | Durable case comment + label |
| Shadow ops | SQL recipe + promote-gate smoke, no desk path | Lean `/ops/shadow` with promote-gate posture |

## Approach

**Desk ops triad** — smallest durable product for each residual (not Zendesk/Jira, not live warehouse charts).

1. Challenge delivery against Micro/E2E webhook sink  
2. FP support pack logged to case (comment + label)  
3. Shadow-vs-primary ops surface on lean nav  
4. Regrade canvas/matrix only after green  

## Non-goals

- External ticketing (Zendesk/Jira/ServiceNow)  
- Multi-provider challenge adapters / customer MFA product  
- Live ClickHouse shadow diff explorer  
- Sift-class queue economics / OR optimization  
- Inflating Risk or overall product to 4.2  

## Design

### A. Challenge delivery

**Intent:** Step-up from CaseDetail is executable against a real webhook in Micro/E2E, not only fail-closed when unset.

**Mechanics:**

- Add a tiny webhook sink usable by Micro/E2E (preferred: small Python HTTP sink script under `scripts/e2e/`, or an in-process test receiver).  
- Wire `TARKA_CHALLENGE_WEBHOOK_URL` in `docker-compose.micro.e2e.yml` (or reset script env) to that sink when running e2e/micro.  
- Extend `test_challenge_dispatch_api.py`: when webhook URL is set (httpx mocked or local sink), expect **200** and `ok: true` / delivery payload. Keep existing 400 / 503 cases.  
- CaseDetail: after `dispatchChallenge`, surface delivery status from response (`ok`, status code, or reason) in toast or a one-line status under the button.  

**Success:** Configured dispatch proves delivery; unconfigured remains honest 503.

### B. FP support pack (durable)

**Intent:** False-positive support kit is an auditable desk action, not clipboard-only.

**Mechanics:**

- Keep existing “Copy support-safe summary” (`buildSupportSafeSummary`).  
- Add **Log FP support pack** on CaseDetail:  
  - `cases.addComment(caseId, tenantId, author, body)` with the support-safe markdown body  
  - `cases.addLabels(..., ["fp_support_pack"])` (or equivalent label API)  
- Small helper `buildFpSupportPackAction(...)` tested with vitest (payload shape).  
- Author from `localStorage tarka.desk_actor` / `"analyst-web"` (match maker-checker actor pattern).  

**Success:** Case timeline shows the pack; label present for queue filters.

### C. Shadow-vs-primary ops surface

**Intent:** Analysts can see promote-gate posture without opening git SQL.

**Mechanics:**

- New page `frontend/src/pages/OpsShadow.tsx` at **`/ops/shadow`**.  
- Add `/ops/shadow` to `LEAN_NAV_PATHS` and App routing/nav (lean group).  
- Page contents (minimum):  
  - Promote-gate contract summary (fintech pack: block underpowered / allow healthy) via thin API **or** static call to existing smoke semantics  
  - Link/path to `scripts/oss/shadow_vs_primary_diff_recipe.sql`  
  - Note that warehouse diff is operator SQL; UI is gate posture + recipe pointer  
- Prefer thin decision-api endpoint `GET /v1/calibration/shadow-promote-gate` returning JSON from `evaluate_kill_criteria` demo metrics (no DB). If endpoint is heavier than needed, frontend may call a tiny OSS JSON produced by the smoke script — prefer live API for honesty.  

**Success:** Lean nav includes Shadow; page shows promote allowed/blocked evidence.

### D. Regrade evidence

**After** A–C green:

- Update `docs/superpowers/canvases/maturity-4-0-regrade.canvas.tsx` (+ Cursor copy): Fraud Ops **4.2–4.4**.  
- Update matrix footnotes in `competitive-score-matrix-2026-04.md`.  
- List evidence: webhook dispatch test, FP pack action, `/ops/shadow`, promote-gate smoke.  

## Acceptance (skeptical checklist)

Fraud Ops may be scored **≥4.2** (band up to **4.4**) only if **all** are true:

1. Challenge dispatch with configured webhook returns success in automated test  
2. CaseDetail can log FP support pack as comment + `fp_support_pack` label  
3. `/ops/shadow` on lean nav shows promote-gate posture + recipe pointer  
4. Regrade canvas/matrix updated **after** the above, not before  

Target **4.3** mid-band if all three land cleanly; **4.2** floor if shadow UI is thin; **4.4** only if challenge e2e also hits a live Micro sink (not only httpx mock).

## Risks

| Risk | Mitigation |
| ---- | ---------- |
| Webhook sink flaky in CI | Prefer httpx mock in pytest; Micro sink optional for local/e2e |
| Label API / comment auth | Reuse existing case-api paths + X-Actor-Id |
| Lean nav audit rejects `/ops/shadow` | Explicitly allow in `LEAN_NAV_PATHS` + audit forbid-list stays brochure-only |
| Score inflation | Acceptance forbids canvas bump until gates pass |

## Evidence map (target)

| Claim | Proof |
| ----- | ----- |
| Challenge executable | `test_challenge_dispatch_api` success path + CaseDetail delivery UI |
| FP pack durable | Vitest helper + CaseDetail action → comment/label |
| Shadow ops surface | `/ops/shadow` + promote-gate JSON + SQL recipe pointer |
| Promote gate still honest | Existing `shadow_promote_gate_smoke.py` in CI |

## Open questions (resolved)

- Earn vs claim: **Earn**  
- Scope: challenge + FP pack + shadow UI (**all three**)  
- Approach: **Desk ops triad**
