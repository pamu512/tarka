# Leftover First-Class (P-left1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** leftover_id API + four thin env gates.

**Architecture:** `leftover_row` alias; env readers in leftover.py / decision_outcome; desk follows leftover_id.

**Tech Stack:** case-api, decision-api, React Leftovers page.

**Spec:** [2026-09-06-leftover-first-class-design.md](../specs/2026-09-06-leftover-first-class-design.md)

**Branch:** `honesty/leftover-first-class` stacked on `#378`

## Global Constraints

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote.
- No `desk_provision.json`.
- No Tarka OSS / third-party desk names in new copy.

---

## File map

| File | Role |
|------|------|
| `case_api/leftover.py` | leftover_id + env helpers |
| `case_api/main.py` | list filter + multi-claim |
| `decision_outcome.py` | FLAG mint env |
| Leftovers desk + client types | leftover_id |

---

### Task 1: leftover_id + env gates

- [ ] Failing leftover_row / FLAG / claim / QA tests
- [ ] Implement helpers and wires
- [ ] Desk leftover_id
- [ ] Commit `feat: leftover_id API and thin leftover env gates`

## Test commands

```
PYTHONPATH=services/shared:services/case-api/src:packages/shared-core python3 -m pytest -c services/case-api/pytest.ini services/case-api/tests/test_leftovers.py -q
PYTHONPATH=services/shared:services/decision-api/src:packages/shared-core python3 -m pytest -c services/decision-api/pytest.ini services/decision-api/tests/test_decision_outcome.py -q
```
