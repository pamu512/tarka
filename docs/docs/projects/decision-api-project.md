# Decision API Project

## Scope

Core real-time decisioning, risk blending, inference normalization, replay/tamper controls, and auditable outputs.

**Typology DSL (OSS #46):** `typology_definitions_v1.json` + `typology_predicate_registry_v1.json`; `GET /v1/admin/typology/predicate-registry`; CI `scripts/policy/validate_typology_dsl.py`. [Service doc — Typology predicate registry](../services/decision-api.md#typology-predicate-registry-oss-46) · [API Reference](../api-reference.md#decision-api).

**Trust / ops UX (OSS #36):** `GET /v1/ops/evaluation-posture` + `GET /v1/slo` feed the console readiness strip. [Service doc](../services/decision-api.md#trust-ops-posture-slo-oss-36) · [API Reference](../api-reference.md#trust-ops-readiness).

## Current Gaps

- Inference calibration is baseline-only and needs stronger confidence tuning.
- Replay/tamper controls need broader scenario coverage and policy hooks.
- Experiment guardrails need deeper interaction safety checks.

## Roadmap

### Now

- Stabilize `inference_context` across all decision paths.
- Harden ingress replay detection and reason-code fidelity.
- Expand endpoint tests for replay/tamper and inference contract.

### Next

- Add configurable inference weighting profiles by tenant/risk policy.
- Add decision explanation ranking with deterministic top drivers.
- Add regression suite for threshold changes and false-positive drift.

### Later

- Pluggable risk strategy framework for vertical-specific blending logic.
- Real-time experiment interaction detector for overlapping controls.
