import pytest
from chitragupta.contract_compat import assert_contract_compatible, capability_matrix_ok
from fastapi import HTTPException


def test_assert_contract_compatible_major_match():
    assert_contract_compatible(plugin_contract="1.4.0", server_contract="1.0.0")


def test_assert_contract_compatible_major_mismatch():
    with pytest.raises(HTTPException) as ei:
        assert_contract_compatible(plugin_contract="2.0.0", server_contract="1.0.0")
    assert ei.value.status_code == 400


def test_capability_matrix():
    ok, miss = capability_matrix_ok(
        required_capabilities={"input": "tabular", "multi_tenant": "true"},
        offered={"input": "tabular", "multi_tenant": "true", "output": "json"},
    )
    assert ok and miss == []

    ok2, miss2 = capability_matrix_ok(
        required_capabilities={"input": "tabular"},
        offered={"input": "json"},
    )
    assert not ok2
    assert miss2
