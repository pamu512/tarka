# Evidence → act + experiment holdout (Waves A / B / C)

**Date:** 2026-08-01  
**Status:** Implemented (Waves A / B / C)

## Waves

### A — Evidence act pack

Case Detail: JSON + ZIP evidence download; act pack summary (`content_sha256`, decision, recommended_action, top drivers) with copy.

### B — Act CTAs

Generate SAR (`POST …/sar/generate`) and create dispute prefilled from case/trace/act pack; navigate to SAR intents / dispute detail.

### C — Experiment holdout surface

Simulation: list `GET /v1/simulation/experiments`; keep underpowered checkbox + guardrail banner; show registry count / recent runs with `events_evaluated` vs min.

## Out of scope

PDF-only procurement redesign, cohort benchmark API, new challenge providers.
