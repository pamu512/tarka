"""Tool error payload hardening."""

from __future__ import annotations

import pytest
from investigation_agent.main import _execute_tool
from investigation_agent.tools import normalize_tool_error_shape


def test_normalize_tool_error_shape_adds_contract_fields():
    out = normalize_tool_error_shape("subgraph", {"error": "graph_disabled"})
    assert out["error"] == "graph_disabled"
    assert out["code"] == "graph_disabled"
    assert out["severity"] == "warning"
    assert out["retryable"] is False
    assert out["upstream"] == "graph_service"
    assert "message" in out


@pytest.mark.asyncio
async def test_execute_tool_invalid_args_emits_structured_error():
    out = await _execute_tool(
        http=None,  # type: ignore[arg-type]
        name="get_case",
        arguments={"case_id": ""},
        tenant_id="demo",
        analyst_id="analyst-1",
    )
    assert out["error"] == "invalid_tool_arguments"
    assert out["code"] == "invalid_tool_arguments"
    assert out["severity"] == "error"
    assert out["upstream"] == "case_api"
