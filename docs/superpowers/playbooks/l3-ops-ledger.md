# L3 ops ledger — four-week live shadow clock

**Status:** **NOT STARTED**  
**Updated:** 2026-08-06  
**Playbook:** [2026-08-05-shadow-four-week-critical.md](./2026-08-05-shadow-four-week-critical.md)  
**Sim (not L3):** `scripts/oss/shadow_four_week_sim.py` → banner `NOT PRODUCTION L3`

## Honesty

Starting this ledger does **not** start L3. L3 starts when Week 1 checklist is completed on a **named live tenant** with shadow + host action log. Sim runs never advance this ledger.

## Clock

| Field | Value |
| --- | --- |
| Tenant id | _pending operator_ |
| Week 1 start (UTC date) | _not set_ |
| Week 4 end (UTC date) | _not set_ |
| Shadow evaluate enabled | no |
| Host action log sink | no |
| Label join / ECE on real labels | no |

## Week checklist (live only)

Copy rows into dated notes when a week completes. Do not check off from sim.

| Week | Shadow on | Host actions logged | Outcomes joined | Weekly metrics | ECE candidate | Sign-off |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | ☐ | ☐ | ☐ | ☐ | — | ☐ |
| 2 | ☐ | ☐ | ☐ | ☐ | — | ☐ |
| 3 | ☐ | ☐ | ☐ | ☐ | — | ☐ |
| 4 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |

## How to start the clock (operator)

1. Pick named tenant; confirm shadow evaluate + host action export.
2. Set **Week 1 start** above to today’s UTC date.
3. Complete Week 1 checklist in the four-week playbook.
4. Advance weekly; Week 4 requires ECE-gated retrain on **real** labels (`retrain_calibration_ece_gate.py`).
5. Only then update claim materials — never from sim JSON.

## 2026-08-06 session note

In-repo path ready (playbook + sim smoke + ECE script). **Clock not started** — no live tenant / host action sink configured in this environment. Claim lock stays closed for L3 (C5).
