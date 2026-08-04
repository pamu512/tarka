# Golden contracts + hard experiment holdout (Waves A–B)

**Date:** 2026-08-03  
**Status:** Approved (user: go, approach C)

## Wave A — Golden evaluate / device-context

Fixtures under `contracts/golden/` validated against JSON Schema + `EvaluateRequest` parse; CI via `make contract-check` / audit-stubs.

## Wave B — Hard experiment holdout

Filterable experiment list; registry rows record underpowered/holdout_ok; Simulation UI filters + KPI marking.

## Out of scope

Full cross-SDK runtime matrix, SMS/WebAuthn, reliability diagrams.
