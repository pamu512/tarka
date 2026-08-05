# Maturity 4.0–4.2 Hybrid Design

**Date:** 2026-08-05  
**Status:** Approved for execution  
**Decisions:** Score scope = end-user lenses + competitive modules; enrichment = hybrid (partner device/location; build counters/calibration/ops).

## Goal

Lift Engineering, Risk/Strategy, and Fraud Ops lenses and competitive module scores to **4.0–4.2** under evidence-gated acceptance (honest surface, golden E2E, matrix SHA, operator runbook/CI).

## Non-goals

- Native global device reputation / Incognia-class co-presence physics
- Tarka-as-vendor SOC2 Type II
- Hypothetical enterprise TPS marketing in root README

## Waves

| Wave | Outcome |
|------|---------|
| 0 | Honesty Program closed/gated; stub CI; one install story |
| 1 | Golden case loop; `y_label` calibration; counters parity product; typology kill criteria |
| 2 | Fingerprint/Incognia fusion → evaluate/graph/case evidence |
| 3 | QA sampling; production `metadata.shadow`; challenge webhooks; rule telemetry |
| 4 | Harden + formal rescore with evidence SHAs |
| 5 | Evidence gates + smallest ops slice — see [maturity-wave5-design](./2026-08-05-maturity-wave5-design.md) |
| 6 | Honest 4.2 across lenses + six-caps — see [maturity-wave6-design](./2026-08-05-maturity-wave6-design.md) |

## Acceptance rule

A score may claim ≥4.0 only with: no silent stubs in prod; mock-free E2E; competitive matrix evidence; runbook or CI gate.

## Hybrid scoring

Device/Location 4.0 means partner signals are first-class in evaluate → graph → case evidence, not that Tarka owns a cross-customer reputation network.
