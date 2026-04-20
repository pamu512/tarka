# Extending Rules, Connectors, and Graph/ML Modules

## Add a rule or typology

1. Add/update JSON packs under `services/decision-api/rules/`.
2. Validate with:
   - `pytest services/decision-api/tests/test_openapi_contract_files.py`
   - `pytest services/decision-api/tests/test_inference_build.py`
3. Reload in runtime via `POST /v1/admin/rules/reload`.

## Add an external connector

1. Implement provider class in `services/decision-api/src/decision_api/external_signals.py`.
2. Return normalized:
   - `risk_score`,
   - `score_delta`,
   - `tags`,
   - `enrichments`.
3. Add config flags in `decision_api/config.py`.
4. Add tests under `services/decision-api/tests/`.

## Extend graph analytics

1. Add algorithm in `services/graph-service/src/graph_service/algorithms_*.py`.
2. Expose endpoint in `graph_service/main.py`.
3. Include risk reasons that map cleanly to explainability tags.

## Extend ML integration

1. Keep `POST /v1/score` response compatible (`score`, `ml_top_factors`, `ml_summary`).
2. Ensure drift endpoints keep stable shape for dashboards.
3. Add adversarial tests/harnesses under `scripts/experiments/adversarial/`.
