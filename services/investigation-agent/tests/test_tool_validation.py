"""Tool argument validation before dispatch."""

import pytest
from investigation_agent.tool_validation import validate_tool_arguments


class TestValidateToolArguments:
    def test_get_case_requires_case_id(self):
        n, e = validate_tool_arguments("get_case", {})
        assert n is None and e and "case_id" in e.lower()

    def test_get_case_accepts_uuid(self):
        cid = "12345678-1234-1234-1234-123456789abc"
        n, e = validate_tool_arguments("get_case", {"case_id": cid})
        assert e is None and n == {"case_id": cid}

    def test_list_cases_clamps_limit(self):
        n, e = validate_tool_arguments("list_cases", {"limit": 500})
        assert e is None and n["limit"] == 100

    def test_subgraph_requires_entity_id(self):
        n, e = validate_tool_arguments("subgraph", {"depth": 2})
        assert n is None and "entity_id" in (e or "").lower()

    def test_get_decision_audit_requires_uuid_trace(self):
        n, e = validate_tool_arguments("get_decision_audit", {"trace_id": "not-a-uuid"})
        assert n is None and e

    def test_ingest_requires_rows_array(self):
        n, e = validate_tool_arguments("ingest_labeled_rows", {"rows": "nope"})
        assert n is None and "array" in (e or "").lower()

    def test_batch_tools_validate_uuid(self):
        n, e = validate_tool_arguments("get_batch_profile", {"batch_id": "not-uuid"})
        assert n is None and e

        uid = "12345678-1234-5678-9012-123456789abc"
        n, e = validate_tool_arguments("get_batch_profile", {"batch_id": uid})
        assert e is None and n == {"batch_id": uid}

    def test_query_batch_clamps_limit(self):
        uid = "12345678-1234-5678-9012-123456789abc"
        n, e = validate_tool_arguments(
            "query_batch_rows",
            {"batch_id": uid, "offset": 0, "limit": 999},
        )
        assert e is None and n["limit"] == 100

    def test_replay_accepts_rule_arrays(self):
        n, e = validate_tool_arguments(
            "run_replay_ab_comparison",
            {
                "rules_variant_a": [{"id": "r", "when": [{"field": "x", "op": "eq", "value": 1}]}],
                "rules_variant_b": [
                    {"id": "r2", "when": [{"field": "y", "op": "gte", "value": 2}]}
                ],
                "limit": 10,
            },
        )
        assert e is None and n is not None
        assert n["limit"] == 10


@pytest.mark.asyncio
class TestExecuteToolInvalidArgs:
    async def test_get_case_empty_args_returns_structured_error(self):
        from unittest.mock import AsyncMock

        from investigation_agent.main import _execute_tool

        http = AsyncMock()
        out = await _execute_tool(http, "get_case", {}, "t1", "a1")
        assert out.get("error") == "invalid_tool_arguments"
        assert "detail" in out
