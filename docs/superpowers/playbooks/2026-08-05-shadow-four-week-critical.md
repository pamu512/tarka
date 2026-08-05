# Four-week shadow ops playbook (critical L3 path)

**Date:** 2026-08-05  
**Track:** O — Ops loop (L3)  
**Branch base:** `maturity-4-0-local`  
**Spec:** [critical-4-5-parallel-tracks-design.md](../specs/2026-08-05-critical-4-5-parallel-tracks-design.md)

## Honesty banner (read first)

> **Synthetic sim ≠ production L3.**  
> `scripts/oss/shadow_four_week_sim.py` is a **wiring/smoke dry-run only**. Its JSON artifact carries `banner: "NOT PRODUCTION L3"`.  
> **Do not** use sim output, fixture SHA, or this checklist alone to claim L3 or critical 4.5.  
> L3 requires ≥4 consecutive weeks of **live** shadow vs host-action logging, real outcome/label joins, and ECE-gated retrain (Task 7).

## Prerequisites

- [ ] Shadow evaluate contract enabled (`metadata.shadow: true` — see [shadow-and-ab-testing.md](../../docs/guides/shadow-and-ab-testing.md))
- [ ] Host action log sink configured (warehouse / audit export)
- [ ] Outcome / clawback label join path live (`y_label_store`, case disposition)
- [ ] Candidate rules path mounted for shadow evaluator
- [ ] `kill_criteria` promote gate wired (Track P Task 1)
- [ ] ECE-gated retrain script available (Track O Task 7)

## Week 1 — Shadow on + host action log

- [ ] Enable production shadow on target tenant(s) (`metadata.shadow: true`)
- [ ] Confirm shadow rows land in audit / ClickHouse (`shadow_rule_evaluations` or equivalent)
- [ ] Start host action log export (analyst disposition, enforcement, clawback hooks)
- [ ] Baseline weekly insult/$ attribution fields (even if sparse)
- [ ] Record week-1 start date + tenant id in ops ledger
- [ ] Run warehouse diff spot-check: [`shadow_vs_primary_diff_recipe.sql`](../../../scripts/oss/shadow_vs_primary_diff_recipe.sql)

## Week 2 — Outcomes + weekly metrics

- [ ] Join host outcomes to shadow traces (trace_id / entity_id)
- [ ] Compute week-2 precision, recall, insult_proxy (live labels — not sim)
- [ ] Export reliability bins; note proxy-only coverage posture
- [ ] File weekly metrics artifact under `artifacts/` with **live** `mode` field
- [ ] Do **not** promote candidate if `kill_criteria` blockers fire

## Week 3 — Retrain candidate + held-out ECE

- [ ] Export labeled window for retrain (train end ≤ week-2 boundary)
- [ ] Run `scripts/oss/retrain_calibration_ece_gate.py` on **real** labels
- [ ] Held-out report window ECE ≤ threshold (default 0.05) or `--force` logged
- [ ] Load Platt candidate into candidate rules path; shadow evaluator picks it up
- [ ] Re-run week-3 live metrics with new candidate shadow scores

## Week 4 — Promote gate + close loop

- [ ] Complete fourth consecutive week of live shadow + host action logging
- [ ] Compute cumulative precision, recall, insult_proxy on joined labels
- [ ] Run promote gate: `python3 scripts/oss/shadow_promote_gate_smoke.py` (live metrics must pass pack `kill_criteria`)
- [ ] Promote candidate only when gate allows **and** ops sign-off recorded
- [ ] Archive chronological artifact + playbook checklist completion in ops ledger

## Sim wiring (smoke only)

Use before or between live weeks to prove script/CI wiring — **not** as L3 evidence:

```bash
PYTHONPATH=services/decision-api/src:. python3 scripts/oss/shadow_four_week_sim.py \
  --seed 42 --out artifacts/shadow_four_week_sim.json
```

Expected top-level keys: `banner`, `precision`, `recall`, `insult_proxy`.  
Assert `banner == "NOT PRODUCTION L3"`.

Pytest smoke:

```bash
cd services/decision-api && PYTHONPATH=src:. python3 -m pytest tests/test_shadow_four_week_sim_smoke.py -q
```

## Claim lock reminder

| Tier | This playbook contributes |
|---|---|
| L1 | No |
| L2 | No |
| L3 | Only when all four **live** weeks complete + real label retrain + artifacts |

Sim alone → **L3 incomplete** → claim lock stays closed.
