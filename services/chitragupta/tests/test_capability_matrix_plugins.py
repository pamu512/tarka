"""Contract matrix for built-in plugins (issue #62)."""

import pytest
from chitragupta.contract_compat import capability_matrix_ok
from chitragupta.plugin_sdk import get_plugin, seed_builtin_plugins


@pytest.fixture(autouse=True)
def _seed():
    from chitragupta import plugin_sdk as ps

    ps._REGISTRY.clear()
    seed_builtin_plugins()


@pytest.mark.parametrize(
    "plugin_id,required",
    [
        (
            "scorecard.json",
            {"input": "tabular", "output": "json_scorecard", "multi_tenant": "true"},
        ),
        ("bi.export", {"input": "tabular", "output": "warehouse_slice", "multi_tenant": "true"}),
    ],
)
def test_builtin_plugin_capability_matrix(plugin_id: str, required: dict):
    p = get_plugin(plugin_id)
    assert p is not None
    ok, miss = capability_matrix_ok(required_capabilities=required, offered=p.capabilities)
    assert ok, miss


def test_builtin_plugins_support_json_and_csv_emitters():
    for pid in ("scorecard.json", "bi.export"):
        p = get_plugin(pid)
        assert set(p.emitter_targets_supported) >= {"json", "csv"}
