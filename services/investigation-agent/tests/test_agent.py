"""Unit tests for the investigation agent — RBAC, tool dispatch, offline mode."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from investigation_agent.tools import (
    TOOL_DISPATCH,
    _analyst_allowed,
    tool_get_case,
    tool_list_cases,
    tool_subgraph,
    tool_get_entity_tags,
)


# ---------- _analyst_allowed ----------


class TestAnalystAllowed:
    def test_wildcard_allows_everyone(self):
        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "*"
            assert _analyst_allowed("any-user") is True

    def test_explicit_allowlist_allows_listed(self):
        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "alice, bob"
            assert _analyst_allowed("alice") is True
            assert _analyst_allowed("bob") is True

    def test_explicit_allowlist_blocks_unlisted(self):
        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "alice,bob"
            assert _analyst_allowed("charlie") is False

    def test_empty_string_allows_everyone(self):
        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = ""
            assert _analyst_allowed("anyone") is True

    def test_none_allows_everyone(self):
        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = None
            assert _analyst_allowed("anyone") is True


# ---------- Tool Dispatch ----------


class TestToolDispatch:
    def test_dispatch_table_has_all_tools(self):
        expected_tools = {"get_case", "list_cases", "subgraph", "get_entity_tags"}
        assert set(TOOL_DISPATCH.keys()) == expected_tools

    def test_dispatch_maps_to_correct_functions(self):
        assert TOOL_DISPATCH["get_case"] is tool_get_case
        assert TOOL_DISPATCH["list_cases"] is tool_list_cases
        assert TOOL_DISPATCH["subgraph"] is tool_subgraph
        assert TOOL_DISPATCH["get_entity_tags"] is tool_get_entity_tags


# ---------- Tool execution with mocked HTTP ----------


class TestToolGetCase:
    @pytest.mark.asyncio
    async def test_get_case_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "case-1", "status": "open"}
        mock_response.raise_for_status = MagicMock()

        http = AsyncMock()
        http.get = AsyncMock(return_value=mock_response)

        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "*"
            mock_settings.case_api_url = "http://case-api:8002"
            mock_settings.upstream_api_key = ""
            result = await tool_get_case(http, "case-1", "t1", "analyst1")

        assert "case" in result
        assert result["case"]["id"] == "case-1"

    @pytest.mark.asyncio
    async def test_get_case_not_found(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        http = AsyncMock()
        http.get = AsyncMock(return_value=mock_response)

        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "*"
            mock_settings.case_api_url = "http://case-api:8002"
            mock_settings.upstream_api_key = ""
            result = await tool_get_case(http, "missing", "t1", "analyst1")

        assert result == {"error": "not_found"}

    @pytest.mark.asyncio
    async def test_get_case_forbidden(self):
        http = AsyncMock()
        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "bob"
            result = await tool_get_case(http, "case-1", "t1", "alice")

        assert result == {"error": "forbidden"}


class TestToolSubgraph:
    @pytest.mark.asyncio
    async def test_subgraph_graph_disabled(self):
        http = AsyncMock()
        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "*"
            mock_settings.graph_service_url = ""
            result = await tool_subgraph(http, "entity-1", "t1", "analyst1")

        assert result == {"error": "graph_disabled"}


# ---------- Offline mode (no API key) ----------


class TestOfflineMode:
    @pytest.mark.asyncio
    async def test_llm_loop_returns_offline_message(self):
        from investigation_agent.main import _llm_tool_loop

        http = AsyncMock()
        with patch("investigation_agent.main.settings") as mock_settings:
            mock_settings.openai_api_key = ""
            reply, tool_calls = await _llm_tool_loop(
                http, "system prompt", [{"role": "user", "content": "hello"}], "t1", "analyst1"
            )

        assert "offline" in reply.lower()
        assert tool_calls == []
