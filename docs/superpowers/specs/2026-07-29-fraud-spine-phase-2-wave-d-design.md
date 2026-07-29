# Fraud spine Phase 2 — Wave D design

Approved via Phase 2 wave table (2026-07-29). Scope: enforcement adapters.

## Goal

Platform **act** hooks for `allow` / `step_up` / `block`, invoked from
`DecisionOutcomeHandler`, separate from case-api investigation UI.

## Shape

- `decision_api/enforcement.py`
  - `resolve_enforcement_action(decision, recommended_action) → allow|step_up|block`
  - `apply_enforcement_adapters(...)` — metrics + optional signed webhook
    (`TARKA_ENFORCEMENT_WEBHOOK_URL` / `TARKA_ENFORCEMENT_WEBHOOK_SECRET`)
  - Schema `tarka.enforcement/v1`
- Wired from `schedule_decision_outcomes` (background task)
- Publish payload gains `enforcement_action`
- Case create and challenge webhook stay; enforcement does not call case-api

## Mapping

| Input | Action |
|-------|--------|
| `decision == deny` | `block` |
| `recommended_action` in step-up/challenge family | `step_up` |
| else | `allow` |

## Out of scope

SMS/WebAuthn providers, orchestrator action_map changes, frontend (Wave E).
