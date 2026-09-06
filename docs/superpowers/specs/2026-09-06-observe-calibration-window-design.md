# Observe calibration window (P-obs1)

**Date:** 2026-09-06  
**Status:** Design — cut locked in chat (`go`).  
**Branch:** `honesty/observe-calibration-registry` stacked on P-reg1 (`#378` / `feat/desk-demo-vs-product`)  
**Related:** `leftover_promote_gate.py`, `GET /v1/calibration/shadow-promote-gate`, Observe `/ops/shadow`

## Goal

Cannot Promote an Observe draft before a dated calibration window without a RiskArchitect override. Unknown `when.field` still 422 and points at field discover. Auto-promote stays off by default.

## Locked choices

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote.
- No `desk_provision.json`. Window limits are env.
- Empty plane URL = that plane off.
- No `rate` / `baseline_ratio`. No new Rust atom.
- Demo ≠ product. No named third-party desks. Do not call Tarka OSS.
- Extend `desk_promote_gate`. Do not invent a second Promote API.
- Scout map UI is out. Pack writes already reject unknown fields.
- Auto-promote PUT stays. Default remains off.

## Window

Env (defaults):

| Env | Default |
|-----|---------|
| `TARKA_CALIBRATION_MIN_DAYS` | 7 |
| `TARKA_CALIBRATION_MIN_LABELS` | 20 |
| `TARKA_CALIBRATION_MAX_FP` | 0.05 |

`calibration_window` on the shadow-promote-gate payload:

- `ok`, `blockers` (`window_open`, `thin_labels`, `fp_above_cap`)
- the three limits plus measured `days`, `label_count`, `fp_rate`

`days` = now − oldest labeled audit `created_at` (UTC). No labels → `window_open` + `thin_labels`. `fp_rate` only blocks when a number is present (leftover helpfulness). Missing FP does not invent 0.

`desk_promote_gate.requires` includes `calibration_window`. Window blockers join desk blockers.

## Override

`POST /v1/rules/shadow-packs/{draft_id}/promote` accepts `calibration_override_reason` (min 8 chars). JWT must include `RiskArchitect` (or `admin`). Override drops **only** window blockers. Leftover / McNemar / drift / labels still apply. Reason is audited on the activate changelog.

Analysts cannot override.

## Unknown field

Keep 422. Message already says map / registry. Mention `GET /v1/fields/discover` if missing.

## Testing

- Helper: 0 labels → not ok; 20 labels + 7 days + fp 0.01 → ok; fp 0.2 → `fp_above_cap`.
- Gate JSON includes `calibration_window`; desk requires it.
- Promote 409 when window open; RiskArchitect + reason proceeds if other gates are green (or still 409 if leftover blocks).
- Create-pack unknown field still 422 and names discover.

## Success

Cannot Promote an AI/Observe draft before the window without RiskArchitect override. Unknown field cannot silently ship.

## Non-goals

- Scout map-new-feature desk. Hard-delete auto-promote PUT. P-obs2 BYO successor. `desk_provision.json`.
