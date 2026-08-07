# Critical Maturity 4.5 — Parallel Tracks Design

**Date:** 2026-08-05  
**Status:** Approved for planning  
**Branch base:** `maturity-4-0-local` (post Wave 0–6 + missed-mark bridge)  
**Prior critical baseline:** ~3.7 overall / ~3.6 six-cap mean (see [maturity-4-0-regrade.canvas.tsx](../canvases/maturity-4-0-regrade.canvas.tsx))  
**Supersedes claim language:** Wave6 liberal “honest 4.2” — do not re-advertise until this program’s claim lock opens.

## Goal

Raise the **skeptical/critical** six-capability scores so that:

| Rule | Threshold |
|---|---|
| Overall mean | ≥ **4.5** |
| Pillar floor | every six-cap ≥ **4.0** |
| Location (hybrid) | ≥ **4.0** (partner-first; may sit at the floor while other pillars stretch past 4.5) |

Publish a critical **4.5** claim only when evidence tiers **L1 ∧ L2 ∧ L3** are all satisfied.

## Score contract (locked)

- **Bar:** critical / skeptical regrade (same honesty as the 2026-08-05 correction), not liberal brochure scoring.
- **Location semantics:** hybrid partner fusion quality (Fingerprint / Incognia → evaluate → graph → case), **not** a native global device-reputation network.
- **Stretch pillars** (target ≥4.5 each to pull the mean): Inference, Replay/tamper, Counters, Analyst, Rule/risk ops.
- **Floor pillar:** Location hybrid ≥4.0 via partner proof + in-repo co-presence depth.
- **Matrix update:** [competitive-score-matrix-2026-04.md](../../docs/guides/competitive-score-matrix-2026-04.md) and regrade canvas update only when claim lock opens.

## Evidence tiers (claim lock)

| Tier | Name | Required artifacts |
|---|---|---|
| **L1** | In-repo | CI gates green; fixture/tenant-proof SHAs; mock-free E2E smoke; `kill_criteria` hard promote/deploy gate; QA desk e2e PR-gated or scheduled with artifact |
| **L2** | Live named tenant | Partner enrichment on a **named** tenant; evaluate → graph → case evidence; pinned SHA + runbook entry (not fixture-only pin) |
| **L3** | Ops loop | ≥**4 weeks** shadow vs host action; outcome/label join → calibration retrain with held-out ECE gate; weekly insult/$ + attribution; playbook — **sim ≠ production claim** |

**Claim formula:**

```
L1 ∧ L2 ∧ L3 → critical regrade → publish overall ≥4.5 and min pillar ≥4.0
```

Any missing tier → no 4.5 publish (may publish intermediate “L1-only / L2-only” status as **not** 4.5).

## Architecture — Approach C (parallel tracks)

Three tracks run in parallel. Integration happens at shared evaluate/graph/case/ops surfaces; claim unlock waits for all tiers.

```
        ┌──────────────── Track P: Platform (L1) ────────────────┐
Events →│ counters dual-diff · kill_criteria gate · QA PR smoke  │
        │ mock lean · HMAC/integrity (Replay stretch)            │
        └───────────────────────────┬────────────────────────────┘
                                    │
        ┌──────────────── Track R: Partner / Location (L1+L2) ───┐
        │ live tenant fusion proof · co-presence/cohort deepen     │
        │ hybrid location floor ≥4.0                               │
        └───────────────────────────┬────────────────────────────┘
                                    │
        ┌──────────────── Track O: Ops loop (L3) ────────────────┐
        │ 4-week shadow · labels · ECE retrain · weekly economics │
        └───────────────────────────┬────────────────────────────┘
                                    ▼
                         Claim lock → critical 4.5 publish
```

### Track P — Platform (primary L1)

| Work item | Pillar lift | Done when |
|---|---|---|
| Counter Redis dual-write + dual-diff / nightly parity (not dry-run-only) | Counters → ≥4.5 | Parity job writes artifact; OpsCounters shows last run; CI or scheduled gate |
| `kill_criteria` hard gate on rule promote/deploy | Rule/risk ops → ≥4.5 | Promote blocked when kill fires; test + CI |
| QA desk e2e green with artifact (PR-gated smoke or required weekly with upload) | Analyst → ≥4.5 | Workflow artifact proves pass |
| mockData lean-build shrink / desk-strict already on | Analyst / honesty | Lean nav + forbid prod mocks stay green |
| Keep HMAC / integrity CI | Replay → ≥4.5 stretch | Existing gates remain; document MitM ceiling |

### Track R — Partner / location (L1 + L2)

| Work item | Pillar lift | Done when |
|---|---|---|
| Live named-tenant partner fusion proof | Location → ≥4.0 | Runbook + SHA for **live** enrichment path (fixture pin alone insufficient) |
| In-repo co-presence / cohort deepen (graph + policy) | Location → ≥4.0 | Features/tests show cohort/co-presence used in evaluate/graph/case without claiming native vendor network |
| Fusion contract tests remain green | Location / Inference | Fixture smoke still required as L1 regression |

### Track O — Ops loop (L3)

| Work item | Pillar lift | Done when |
|---|---|---|
| Shadow logging vs host action ≥4 weeks | Inference / Analyst | Chronological artifact + playbook checklist complete |
| Label join (outcomes / clawbacks) → Platt/ECE retrain gate | Inference → ≥4.5 | ECE ≤ threshold or `--force` logged; never fit on report window |
| Weekly insult/$ + floor/score attribution | Rule/risk / Ops lens | Analytics/ops summary fields + docs |
| Explicit banner: 28-day **sim** ≠ production L3 | Honesty | README / matrix / playbook |

## Acceptance per pillar (critical)

| Cap | Min | Stretch target | Blocking evidence |
|---|---|---|---|
| Inference | 4.0 | ≥4.5 | Durable labels; proxy-off bins; L3 retrain ECE gate |
| Replay/tamper | 4.0 | ≥4.5 | HMAC/integrity CI; document MitM product ceiling |
| Counters | 4.0 | ≥4.5 | Dual-diff / nightly parity, not dry-run vanity |
| Location (hybrid) | **4.0** | 4.0–4.2 | L2 live tenant proof + co-presence depth |
| Analyst | 4.0 | ≥4.5 | Challenge desk path + QA e2e artifact |
| Rule/risk ops | 4.0 | ≥4.5 | kill_criteria hard promote gate |

## Integration / merge discipline

- Tracks may land on feature branches; merge to the maturity line only with track-local tests green.
- Do **not** bump matrix cells to 4.5 in the same PR as incomplete L2/L3.
- Shared surfaces (evaluate, graph evidence, case desk, analytics): prefer one owner PR per surface conflict; rebase often (Approach C risk).

## Error handling / honesty

- Missing live tenant credentials → Track R stays L1-only; claim lock closed.
- Shadow week gaps → L3 incomplete; no 4.5 publish.
- ECE fail on retrain → keep prior calibrator; exit non-zero unless forced (force logged).
- Soft-floor / partner absence → skip elevation; do not invent signals.

## Non-goals

- Native global device reputation / Incognia-class co-presence physics as a Tarka-owned network
- Tarka-as-vendor SOC2 Type II
- Sift-class queue OR marketing claims
- Hypothetical enterprise TPS in root README
- Claiming 4.5 from in-repo sim or fixture SHA alone

## Success criteria

1. Critical regrade canvas shows overall ≥4.5 and every pillar ≥4.0.
2. L1, L2, L3 artifacts linked from the matrix / program status.
3. Competitive matrix updated with evidence notes (not blanket 4.5 without links).
4. README / program docs state production 4.5 is ops-gated by the 4-week loop.

## Deliverable sequencing

1. This design spec (committed).
2. Implementation plan with parallel Track P / R / O task lists + claim-lock checklist.
3. Execute tracks in parallel; integrate at shared surfaces.
4. Critical regrade + matrix publish only when L1 ∧ L2 ∧ L3 hold.
