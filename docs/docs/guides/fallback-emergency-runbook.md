# Decisioning Fallback Emergency Runbook

This runbook defines emergency controls when upstream dependency instability threatens decision quality or latency SLOs.

## Decision posture modes

- **Normal mode:** standard blend and enrichers active (`SCORE_BLEND_STRATEGY=average|max`).
- **Degraded-safe mode:** keep evaluate online with fail-open enrichers and explicit `fallback_reason`.
- **Containment mode:** temporarily force rules-only scoring (`SCORE_BLEND_STRATEGY=rules_only`) while preserving audit traces.

## Trigger conditions

- Sustained circuit-open alerts for critical dependencies (`graph`, `feature`, `ml`, `opa`, `calibration`, `counter`, `location`, `external`).
- P95 evaluate latency breaches with rising timeout-driven `step_trace` failures.
- Replay drift budget breaches after policy/model rollouts.

## Emergency actions (ordered)

1. Confirm active failures with:
   - `GET /v1/slo`
   - `GET /v1/ops/evaluation-posture`
   - Prometheus metrics (`tarka_circuit_open_total_*`, `tarka_eval_step_*`).
2. Isolate failing upstream(s):
   - Apply tenant kill-switches where available (`disable_graph`, `disable_ml`, `disable_opa`, `disable_feature_service`, `disable_entity_lists`).
3. Contain impact:
   - Set `SCORE_BLEND_STRATEGY=rules_only` if drift/latency risk is high.
   - Keep `fallback_reason` and `step_trace` enabled for postmortem attribution.
4. Validate containment:
   - Run `scripts/chaos/chaos_smoke.py` baseline checks (and dependency matrix if using full profile).
   - Run `scripts/replay/replay_decision_logs.py` with budget flags.
5. Recover gradually:
   - Re-enable enrichers one dependency at a time.
   - Monitor circuit-open and drift-rate budgets for at least one window before full restore.

## Recommended budget gates

- `scripts/replay/replay_decision_logs.py --max-allowed-decision-change-rate <x> --max-allowed-drift-rate <y>`
- Keep explicit thresholds in release playbooks per tenant reliability profile.

## Post-incident checklist

- Record root cause category (`policy_drift`, `model_drift`, `dependency_drift`, `data_drift`).
- Attach representative trace IDs and replay output summary.
- Update timeout/retry/circuit policies and chaos matrix coverage if gaps were found.
