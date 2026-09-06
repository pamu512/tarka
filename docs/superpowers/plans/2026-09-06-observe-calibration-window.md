# Observe Calibration Window (P-obs1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dated calibration window on `desk_promote_gate` with RiskArchitect override only.

**Architecture:** Pure helper + wire into `compute_desk_and_leftover_gates`. Promote POST optional override reason. Observe UI shows window status.

**Tech Stack:** Python decision-api, existing leftover/desk gates, React Observe page.

**Spec:** [2026-09-06-observe-calibration-window-design.md](../specs/2026-09-06-observe-calibration-window-design.md)

**Branch:** `honesty/observe-calibration-registry` stacked on `#378`

## Global Constraints

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote.
- No `desk_provision.json`. Env limits only.
- No Tarka OSS / third-party desk names in new copy.

---

## File map

| File | Role |
|------|------|
| Create: `decision_api/calibration_window.py` | Helper + env defaults |
| Modify: `leftover_promote_gate.py` | Include window in desk |
| Modify: `rule_api.py` promote | Override reason + role |
| Modify: `calibration_api.py` | Pass through window |
| Modify: Observe `OpsShadow.tsx` | Show window; override box |
| Modify: field-reject copy | discover URL |

---

### Task 1: Helper + desk wire

- [ ] Failing helper tests
- [ ] Implement helper; `_desk_promote_from_parts` takes window
- [ ] Gate tests see `calibration_window`
- [ ] Commit `feat: calibration window on desk promote gate`

### Task 2: Override + UI + discover copy

- [ ] Promote override tests
- [ ] Wire POST query; Observe status row
- [ ] Discover mention on unknown field 422
- [ ] Commit `feat: RiskArchitect calibration window override`

## Test commands

```
PYTHONPATH=services/shared:services/decision-api/src:packages/shared-core python3 -m pytest -c services/decision-api/pytest.ini services/decision-api/tests/test_calibration_window.py services/decision-api/tests/test_shadow_promote_gate_api.py -q
```
