# Could-be-better wave design

**Date:** 2026-08-05  
**Status:** Implemented  
**Source:** End-user product review “Could be better” + bridge Partials  
**Plan:** `docs/superpowers/plans/2026-08-05-could-be-better.md`

## Goal

Close residual “Could be better” findings without raising hybrid scores above 4.2.

## Slices

| ID | Finding | Disposition | Evidence |
|----|---------|-------------|---------|
| A | Degraded-mode desk UX | **Closed** | `CapabilityChips` + load `DegradedModeBanner` + down/posture warnings |
| B | Support / FP kit | **Closed** | `false-positive-support-kit.md` + copy summary |
| C | Production shadow as product | **Closed** | SQL recipe + promote-gate smoke + guide rewrite |
| D1 | QA Playwright CI | **Closed** | `ops-qa-desk-e2e.yml` weekly + dispatch |
| D2 | Live partner proof | **Waiver** | Fixture pin CI; live SHA or WAIVED line |
| E | Honesty before vertical UIs | **Closed** | STUB_REGISTER + demo badges default off |

## Non-goals

Native device network, vendor SOC2, full mockData deletion, matrix > 4.2.
