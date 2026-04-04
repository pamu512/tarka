# Decision API Project

## Scope

Core real-time decisioning, risk blending, inference normalization, replay/tamper controls, and auditable outputs.

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
