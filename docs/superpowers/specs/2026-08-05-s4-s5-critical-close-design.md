# S4 + S5 — close critical could-be-better (design)

Date: 2026-08-05  
Status: approved for implementation

## S5 — `/install` hard gate

`POST /v1/rules/vertical-packs/{name}/install` must accept the same metrics body as promote and run `evaluate_kill_criteria`. Fail → **409** with blockers. Success → 201 + install.

## S4 — counters `matched:true` in CI

PR CI runs `counter_parity_dual_diff.py --mode dual_diff` against Redis service and fails unless artifact `matched == true`. Dry-run alone is not ops proof.
