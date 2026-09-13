"""Guard: decision_api.shadow_evaluator (CH shadow_rule_evaluations writer) removed.

The module had zero production importers — the live shadow path is shadow.py +
main._run_shadow_evaluation (NATS fraud.shadow.*). These guards keep it dead.
"""

import importlib


def test_shadow_evaluator_module_removed():
    try:
        importlib.import_module("decision_api.shadow_evaluator")
    except ModuleNotFoundError:
        return
    raise AssertionError("decision_api.shadow_evaluator should be deleted")


def test_config_no_shadow_evaluator_fields():
    from decision_api.config import settings

    fields = set(type(settings).model_fields)
    for name in (
        "shadow_evaluator_enabled",
        "shadow_evaluator_timeout_seconds",
        "candidate_rules_path",
        "clickhouse_shadow_evaluations_table",
    ):
        assert name not in fields, f"stale config field: {name}"
