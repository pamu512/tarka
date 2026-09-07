# Backtest before promote

Marble-style gate: bind a **succeeded** warehouse backtest to vertical pack `kill_criteria` before install/promote.

## API

| Surface | Path |
|---|---|
| Posture | `GET /v1/rules/backtest-before-promote-posture` |
| Enqueue | `POST /v1/rules/backtest/jobs` |
| Status | `GET /v1/rules/backtest/jobs/{job_id}` |
| Install/promote body | `backtest_job_id` (optional unless required) |

## Require mode

```bash
export TARKA_REQUIRE_BACKTEST_BEFORE_PROMOTE=1
```

When set, omit/`pending`/`failed` jobs → **409** with `backtest_promote_gate.blockers`.

When unset, `backtest_job_id` omitted → **waived** (simulation metrics only — legacy).

## UI

- Rules → Vertical Packs → optional backtest job id
- Ops → Backtest jobs (`/ops/backtest`)
- OpsShadow → backtest-before-promote panel

## L2 leftover / override → Observe

A leftover or HIL override can mint an Observe draft (`mode=shadow`). If the draft is AI-authored, a backtest pass is **required** before it lands in Observe (`409 backtest_required`). Human drafts may skip with actor + reason. This is not auto-Promote and not a live hop.
