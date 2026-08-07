# Maturity Wave 6 Design (honest 4.2 across lenses + six-caps)

**Date:** 2026-08-05  
**Status:** In execution  
**Bar:** Score ≥4.2 only with evidence (UI or API + test/CI + runbook). Hybrid device/location = partner fusion quality, not native vendor network.

## Targets (all → 4.2)

Lenses: Engineering, Risk/Strategy, Fraud Ops.  
Six-caps: Inference, Replay/tamper, Counters, Location (hybrid), Analyst, Rule/risk ops.

## Workstreams

1. **Ops QA desk** — wire `qa-sample` / `qa-review` / `qa-metrics` into frontend `/ops/qa`
2. **Counter parity product** — CI writes `counter_parity_last.json`; OpsCounters shows `last_parity_run`; job API tests
3. **Fusion E2E** — fixture signals → features/tags/graph hints → audit `partner_evidence` contract test
4. **Tamper gate** — CI script proves request-signature middleware rejects bad HMAC when secret set; integrity ops documented
5. **Rule telemetry durability** — file-backed hit counts (survive process bounce in single-node ops)
6. **Calibration posture** — OpsCalibration surfaces `posture.healthy`; unhealthy banner
7. **Matrix** — set 4.2 only where gates pass; remaining structural ceilings named

## Non-goals

- Native global device reputation / Incognia physics
- Tarka-as-vendor SOC2 Type II
