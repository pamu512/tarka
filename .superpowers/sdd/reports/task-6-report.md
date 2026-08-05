# Task 6 Report — Four-week shadow playbook + sim wiring

**Status:** DONE  
**Branch:** `maturity-4-0-local`  
**Date:** 2026-08-05

## Deliverables

| File | Role |
| --- | --- |
| `docs/superpowers/playbooks/2026-08-05-shadow-four-week-critical.md` | Weeks 1–4 ops checklist; explicit sim ≠ L3 |
| `scripts/oss/shadow_four_week_sim.py` | Synthetic chronological dry-run; writes JSON with `banner: "NOT PRODUCTION L3"` |
| `services/decision-api/tests/test_shadow_four_week_sim_smoke.py` | Asserts banner + metric keys |

## Verification

```bash
PYTHONPATH=services/decision-api/src:. python3 scripts/oss/shadow_four_week_sim.py --seed 42 --out artifacts/shadow_four_week_sim.json
cd services/decision-api && PYTHONPATH=src:. python3 -m pytest tests/test_shadow_four_week_sim_smoke.py -q
```

- Sim exit 0; artifact keys: `banner`, `precision`, `recall`, `insult_proxy`, four `weeks`
- `banner == "NOT PRODUCTION L3"` ✓
- Pytest: 1 passed

## Honesty

- **L3 not claimed.** Sim is wiring/smoke only per design spec and playbook banner.
- Live ≥4-week shadow + label join + ECE retrain (Task 7) still required for claim lock.

## Commit

```
feat: four-week shadow playbook and non-claiming sim for L3 path
```
