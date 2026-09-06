# BYO Successor Gates (P-obs2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Env-gated BYO successor suggest on existing scout-pack; host slip + 409 unchanged.

**Architecture:** Pure helpers next to `slip_draft_would_clobber`. `create_scout_pack` 403s successor-shaped bodies when env is off; rewrites `slip_critic`. Observe copy names human Promote.

**Tech Stack:** Python decision-api, existing scout-pack tests, React ObserveEasePanel.

**Spec:** [2026-09-06-byom-successor-gates-design.md](../specs/2026-09-06-byom-successor-gates-design.md)

**Branch:** `honesty/byom-successor-gates` stacked on `#378`

## Global Constraints

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote / demote live.
- No `desk_provision.json`. Env gate only.
- No Tarka OSS / third-party desk names in new copy.

---

## File map

| File | Role |
|------|------|
| Modify: `live_rule_slip.py` | `is_slip_successor_suggest`, `byo_successor_suggest_enabled` |
| Modify: `rule_api.py` `create_scout_pack` | 403 + rewrite authored_by |
| Modify: `ObserveEasePanel.tsx` | successor copy |
| Test: `test_live_rule_slip.py`, `test_scout_pack_api.py`, `ObserveEasePanel.test.tsx` | TDD |

---

### Task 1: Helpers + scout-pack gate

- [ ] Failing helper + scout-pack tests
- [ ] Implement helpers; wire create_scout_pack
- [ ] Commit `feat: env-gate BYO successor suggest on scout-pack`

### Task 2: Observe copy

- [ ] Failing panel test for successor sentence
- [ ] Update ObserveEasePanel
- [ ] Commit `feat: Observe copy — human owns successor Promote`

## Test commands

```
PYTHONPATH=services/shared:services/decision-api/src:packages/shared-core python3 -m pytest -c services/decision-api/pytest.ini services/decision-api/tests/test_live_rule_slip.py services/decision-api/tests/test_scout_pack_api.py services/decision-api/tests/test_live_rule_slip_api.py -q
```
