# Desk UI scorecard (T1–T6)

UX0 stream exit gate. Professional evaluate desk — leftovers, receipts, Observe→Promote. Not a consumer app. Not a case CRM.

**Primary metric:** clicks and steps to complete a core task (minimum expert path, MEP). Task success, time, and errors support the click bar. They do not replace it.

**Vocab lock:** leftover / evaluate hold is **REVIEW**. Do not revive leftover FLAG. A Sep 8 walk that said leftover FLAG means leftover REVIEW on tip.

**Not a ship gate:** consumer SUS / SEQ. Use them only to explain feel after the click bar is scored.

## How to count

- **Click:** intentional activation (primary click/tap, keyboard activate). Exclude scroll-only and hover-only. Count backtracks.
- **Step:** screen, panel, or dialog transition.
- **MEP:** expert path once, then walk as a competent analyst (no memorized selectors).
- **Good:** ≤ MEP + 1 click and no extra panel hop (or = MEP).
- **OK:** ≤ 1.5× MEP clicks *and* ≤ MEP + 1 step.
- **Bad:** > 1.5× MEP, or a forced detour through unrelated surfaces (settings, unrelated lists) to finish a desk core task.

## Dimensions (desk bar)

Thresholds are for trained analysts on daily RiskOps work.

| # | Dimension | Good | Notes |
|---|-----------|------|-------|
| 1 | Clicks / steps *(primary)* | ≤ MEP + 1 click, no extra hop | Product lock |
| 2 | Task success | ≥ 95% on core tasks for people who know the domain | Missed receipt-why or wrong pack is an audit fail |
| 3 | Time on task | ≤ 1.25× expert baseline | Compare to EB for that task |
| 4 | Error / recoverability | 0 consequential; ≤ 1 recoverable slip the UI helps fix | Silent Promote or missing why is consequential |
| 5 | Status visibility | Receipt-why and fired pack visible on evaluate / leftover context | Do not hide why in logs only |
| 6 | Recognition over recall | Pack name / decision on-screen or one labeled control | No memorized pack UUID |
| 7 | Empty-state honesty | Explicit empty / plane off; no false connected | Empty URL = plane off |
| 8 | Pattern consistency | Same verbs: REVIEW, Open receipt, Promote, Propose Demote | Do not mix leftover FLAG back in |

SEQ (1–7) after a task and SUS after a full walk are optional session feel. They must not override the click/step bar.

## Core tasks

Start each walk from the start state. Success criteria are all-or-nothing.

| # | Task | Start | Success (all must be true) | MEP (clicks / steps) | Automated owner |
|---|------|-------|----------------------------|----------------------|-----------------|
| **T1** | Open leftover **REVIEW** + see receipt-why | `/leftovers` shows ≥1 leftover REVIEW evaluate item | Item open; decision = REVIEW visible; **why / receipt** readable in evaluate context (or one labeled Open receipt) | **1 / 1** — Open receipt → Decisions receipt + `PackWhyStrip` | `src/desk-ui-scorecard.test.tsx` (T1). Also `src/pages/Leftovers.test.tsx` (`opening leftover receipt reaches the receipt-why path`) |
| **T2** | Override with why | Leftover REVIEW row | Observe draft created; **why required** (≥8 chars) and saved; status visible; leftover brief is not the why | **2 / 0** — type why + Create draft. Fail if why optional or silent | `src/desk-ui-scorecard.test.tsx` (T2). Also `src/components/L2DraftButtons.test.tsx`, `src/pages/Leftovers.test.tsx` |
| **T3** | Promote Observe pack | Pack in Observe (`/ops/shadow`, not live) | Promote found; **confirm** (pack name, becomes live); Cancel leaves Observe; no silent Promote | **2 / 1** — Promote draft → Confirm. Cancel = 0 Promote calls | `src/desk-ui-scorecard.test.tsx` (T3). Also `src/components/ObserveEasePanel.test.tsx` |
| **T4** | Find which pack fired | Receipt / Decisions row that references ≥1 pack | Analyst names the firing pack from the UI without a memorized UUID | **0 / 0** on the Decisions list (pack name on the row). Else **1 / 1** — Open receipt → `PackWhyStrip` | `src/desk-ui-scorecard.test.tsx` (T4). Also `src/pages/Decisions.test.tsx` (UX0.6 path) |
| **T5** | Late-label bind | Event that needs a late label | Label bound to the receipt; bound state visible; no orphan / ambiguous label. FP may mint an Observe soften draft | Webhook path, not a desk CRM form | **Owner:** `services/decision-api/tests/test_late_label_hop.py` (`test_fp_binds_receipt_and_opens_observe_soften`). No frontend late-label page — do not invent one |
| **T6** | Empty-URL honesty (PlaneOff) | Plane URL empty / missing (or clear it) | UI does **not** claim connected / success; shows plane off / not configured; no blank crash; empty URL = plane off | **0** extra clicks — deep link renders PlaneOff | **Owner:** `src/pages/PlaneOff.test.tsx` (graph + Advise). Also `src/config/leanNav.test.ts` |

`PackWhyStrip` has no dedicated test file; T1 / T4 mount it through Leftovers and Decisions.

## CI vs live walk

| Gate | What runs | Required to ship UX0? |
|------|-----------|------------------------|
| Unit / component | `npm test` in `frontend/` (CI job `build-frontend` → `npm run test -w tarka-ui`) including `src/desk-ui-scorecard.test.tsx` | **Yes** |
| Focused owners | `npm test -- src/pages/Decisions.test.tsx src/pages/Leftovers.test.tsx src/pages/PlaneOff.test.tsx src/components/ObserveEasePanel.test.tsx src/desk-ui-scorecard.test.tsx` | **Yes** (subset of the above) |
| T5 API | `pytest services/decision-api/tests/test_late_label_hop.py` | Yes for late-label bind; not a frontend click walk |
| Full browser | `E2E_SCORECARD=1 npx playwright test e2e/desk-ui-scorecard.spec.ts` from `frontend/` | **No.** Manual / nightly. Spec **skips when the desk is down** or when `E2E_SCORECARD` is unset. Do not add it as a required PR check |

Default Playwright `global-setup` still waits on evaluate health. If the desk is down, do not treat that as a scorecard fail — leave `E2E_SCORECARD` unset or skip.

## Live-walk sheet

Copy per session. Score Good / OK / Bad on dimension 1 first.

| Field | Value |
|-------|-------|
| Date / time (HKT) | |
| Build / env / URL | |
| Walker (expert / analyst / fresh) | |
| Rater | |

| Task | Success Y/N | Clicks | Steps | MEP clicks | Ratio | Time (s) | EB (s) | Errors (R/C) | Status 0–2 | Honesty | Evidence |
|------|-------------|--------|-------|------------|-------|----------|--------|--------------|------------|---------|----------|
| T1 leftover REVIEW + receipt-why | | | | 1 | | | | | | — | |
| T2 Override + why | | | | 2 | | | | | | — | |
| T3 Promote Observe | | | | 2 | | | | | | — | |
| T4 Which pack fired | | | | 0 | | | | | | — | |
| T5 Late-label bind | | | | — | | | | | | — | |
| T6 Empty-URL honesty | | | | 0 | | | | | | Y/N | |

**Primary bar:** Pass only if every walked core task is Good or OK on clicks/steps.

**Ship desk?** Yes / Yes with fixes / No — click bar first. Not SUS.

## Out of scope

- Consumer SUS as a ship gate
- Case CRM tasks, dispute queues, ticket inboxes
- Named incumbent / vendor comparisons
- UX0.8 brochure hygiene
- Changing evaluate authority (Rust evaluates; model never ALLOW / DENY / Promote / demote)
- Auto-demote; Propose→Confirm Demote stays human-only
- emit_only default; empty URL = plane off

See [analyst control loop](analyst-control-loop.md). Claim language: [CLAIM_LOCK](../../compliance/CLAIM_LOCK.md).
