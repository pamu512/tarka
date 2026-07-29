# Fraud spine Phase 2 — Wave E design

Approved via Phase 2 wave table (2026-07-29). Scope: frontend mockData shrink +
versioned decision/ops clients.

## Goal

Shrink the god `mockData.ts` / `client.ts` surface for decision + ops UI so new
work targets versioned contracts only.

## Shape

1. **`mockData.decisions.ts`** — evaluate, replay, challenge policies, SLO,
   evaluation/governance posture, policy-set posture, counters catalog, audit,
   calibration. Dispatched early from `getMockResponse`.
2. **`api/v1/decisions.ts`** — versioned re-export of `decisions` + `decisionsOps`
   helpers. Ops/decision pages import from here.
3. **Client** — `decisions.policyPosture()` for `GET /v1/policy/posture`.

## Pages moved to versioned import

AnalystReadinessBar, Settings, OpsCounters, OpsCalibration, AuditLogExplorer.

## Out of scope

Full `client.ts` split; remaining decision routes (rules/lists/simulation) stay
in `mockData.ts` for a later slice.
