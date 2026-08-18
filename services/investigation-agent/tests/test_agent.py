"""Unit tests for the investigation agent — RBAC, tool dispatch, offline mode."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from investigation_agent.tools import (
    TOOL_DEFINITIONS,
    TOOL_DISPATCH,
    _analyst_allowed,
    _validate_depth,
    tool_export_outcome_labeled_dataset,
    tool_get_case,
    tool_get_entity_tags,
    tool_ingest_labeled_rows,
    tool_list_cases,
    tool_run_replay_ab_comparison,
    tool_subgraph,
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
        expected_tools = {
            "search_knowledge",
            "compare_entity_queue_snapshot",
            "get_batch_profile",
            "query_batch_rows",
            "aggregate_batch_column",
            "get_case",
            "list_cases",
            "subgraph",
            "get_entity_tags",
            "get_entity_velocity",
            "get_decision_audit",
            "get_decision_chain",
            "get_decision_impact",
            "subgraph_with_velocity",
            "export_outcome_labeled_dataset",
            "ingest_labeled_rows",
            "get_stored_labeled_dataset",
            "run_replay_ab_comparison",
            "screen_sanctions_pep",
            "summarize_adverse_media",
            "consolidate_entity_profile",
            "graph_risk_narrative",
            "evaluate_entity_trend",
            "propose_case_status",
        }
        assert set(TOOL_DISPATCH.keys()) == expected_tools

    def test_dispatch_maps_to_correct_functions(self):
        from investigation_agent.tools import (
            tool_aggregate_batch_column,
            tool_get_batch_profile,
            tool_get_decision_audit,
            tool_get_entity_velocity,
            tool_get_stored_labeled_dataset,
            tool_query_batch_rows,
            tool_subgraph_with_velocity,
        )

        assert TOOL_DISPATCH["get_batch_profile"] is tool_get_batch_profile
        assert TOOL_DISPATCH["query_batch_rows"] is tool_query_batch_rows
        assert TOOL_DISPATCH["aggregate_batch_column"] is tool_aggregate_batch_column
        assert TOOL_DISPATCH["get_case"] is tool_get_case
        assert TOOL_DISPATCH["list_cases"] is tool_list_cases
        assert TOOL_DISPATCH["subgraph"] is tool_subgraph
        assert TOOL_DISPATCH["get_entity_tags"] is tool_get_entity_tags
        assert TOOL_DISPATCH["get_entity_velocity"] is tool_get_entity_velocity
        assert TOOL_DISPATCH["get_decision_audit"] is tool_get_decision_audit
        assert TOOL_DISPATCH["subgraph_with_velocity"] is tool_subgraph_with_velocity
        assert (
            TOOL_DISPATCH["export_outcome_labeled_dataset"] is tool_export_outcome_labeled_dataset
        )
        assert TOOL_DISPATCH["ingest_labeled_rows"] is tool_ingest_labeled_rows
        assert TOOL_DISPATCH["get_stored_labeled_dataset"] is tool_get_stored_labeled_dataset
        assert TOOL_DISPATCH["run_replay_ab_comparison"] is tool_run_replay_ab_comparison


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
        http.get.assert_called_once()
        assert http.get.call_args.kwargs.get("params") == {"tenant_id": "t1"}

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


def test_validate_depth_allows_five_clamps_six():
    assert _validate_depth(5) == 5
    assert _validate_depth(6) == 5


@pytest.mark.asyncio
async def test_subgraph_tool_passes_through_node_risk(monkeypatch):
    http = AsyncMock()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "nodes": [
            {
                "id": "u1",
                "scored": True,
                "risk_score": 20,
                "risk_factors": ["fast_growth_1h:5"],
            }
        ],
        "edges": [],
    }
    resp.raise_for_status = MagicMock()
    http.get = AsyncMock(return_value=resp)
    monkeypatch.setattr("investigation_agent.tools.settings.graph_service_url", "http://graph.test")
    monkeypatch.setattr("investigation_agent.tools._analyst_allowed", lambda a: True)
    from investigation_agent.tools import tool_subgraph as subgraph_fn

    out = await subgraph_fn(http, "u1", "t", "analyst1", depth=5)
    assert out["nodes"][0]["risk_score"] == 20
    http.get.assert_awaited()
    assert http.get.await_args.kwargs["params"]["depth"] == 5


def test_mule_layering_playbook_cites_growth_factors():
    from investigation_agent.playbooks import playbook_system_append

    fragment = playbook_system_append("mule_layering")
    assert "fast_growth_1h" in fragment
    assert "fast_growth_24h" in fragment
    assert "high_degree_vs_peers" in fragment
    assert "depth up to 5" in fragment


def test_account_takeover_playbook_cites_growth_factors():
    from investigation_agent.playbooks import playbook_system_append

    fragment = playbook_system_append("account_takeover")
    assert "fast_growth_1h" in fragment
    assert "fast_growth_24h" in fragment
    assert "high_degree_vs_peers" in fragment


def test_persona_workflow_cites_graph_node_risk():
    from investigation_agent.personas import build_copilot_system_prompt

    prompt = build_copilot_system_prompt("investigation")
    assert "Cite fast_growth_* / high_degree_vs_peers only when present" in prompt
    assert "Do not fetch a 5-hop subgraph on every turn" in prompt


def test_subgraph_tool_descriptions_include_node_risk_fields():
    texts = []
    for t in TOOL_DEFINITIONS:
        fn = t.get("function") or {}
        if fn.get("name") in {"subgraph", "subgraph_with_velocity"}:
            texts.append(fn.get("description") or "")
    blob = " ".join(texts)
    assert "scored" in blob
    assert "risk_score" in blob
    assert "relation_growth_1h" in blob
    assert "relation_growth_24h" in blob
    assert "risk_factors" in blob
    assert "clamped 1–5" in blob or "clamped 1-5" in blob


# ---------- Offline mode (no API key) ----------


class TestExportOutcomeLabeledDataset:
    @pytest.mark.asyncio
    async def test_export_merges_case_and_dispute(self):
        case_resp = MagicMock()
        case_resp.status_code = 200
        case_resp.raise_for_status = MagicMock()
        case_resp.json.return_value = {
            "items": [
                {
                    "id": "c1",
                    "trace_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "entity_id": "e1",
                    "labels": ["confirmed_fraud"],
                }
            ]
        }
        disp_resp = MagicMock()
        disp_resp.status_code = 200
        disp_resp.raise_for_status = MagicMock()
        disp_resp.json.return_value = {
            "items": [
                {
                    "id": "d1",
                    "trace_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "entity_id": "e1",
                    "outcome": "false_positive",
                    "status": "resolved",
                }
            ]
        }
        http = AsyncMock()
        http.get = AsyncMock(side_effect=[case_resp, disp_resp])

        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "*"
            mock_settings.case_api_url = "http://case:8002"
            mock_settings.upstream_api_key = ""
            out = await tool_export_outcome_labeled_dataset(http, "t1", "a1", 10, 10, True)

        assert out.get("total") == 1
        assert out["items"][0]["y_label"] == "legitimate"
        assert out["items"][0]["source"] == "dispute"


class TestIngestLabeledRows:
    @pytest.mark.asyncio
    async def test_ingest_posts_to_case_api(self):
        tid = "12345678-1234-1234-1234-123456789abc"
        post_ok = MagicMock()
        post_ok.status_code = 200
        post_ok.json.return_value = {
            "ok": True,
            "added": 1,
            "stored_total": 1,
            "max_per_analyst": 500,
        }
        post_clear = MagicMock()
        post_clear.status_code = 200
        post_clear.json.return_value = {
            "ok": True,
            "added": 0,
            "stored_total": 0,
            "max_per_analyst": 500,
        }
        http = AsyncMock()
        http.post = AsyncMock(side_effect=[post_ok, post_clear])

        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "*"
            mock_settings.case_api_url = "http://case:8002"
            mock_settings.upstream_api_key = ""
            r1 = await tool_ingest_labeled_rows(
                http,
                "t1",
                "a1",
                [{"trace_id": tid, "label": "fraud", "source": "manual"}],
                clear_existing=True,
            )
            assert r1.get("added") == 1
            assert "investigation-label-drafts/batch" in http.post.call_args[0][0]
            body = http.post.call_args.kwargs.get("json") or http.post.call_args[1]["json"]
            assert body["analyst_id"] == "a1"
            assert body["clear_existing"] is True
            r2 = await tool_ingest_labeled_rows(http, "t1", "a1", [], clear_existing=True)
            assert r2.get("stored_total") == 0


class TestReplayAbComparison:
    @pytest.mark.asyncio
    async def test_ab_calls_replay_twice(self):
        rules_a = [
            {"id": "r1", "when": [{"field": "amount", "op": "gte", "value": 100}], "score_delta": 5}
        ]
        rules_b = [
            {
                "id": "r2",
                "when": [{"field": "amount", "op": "gte", "value": 200}],
                "score_delta": 10,
            }
        ]
        replay_json = {
            "tenant_id": "t1",
            "events_evaluated": 3,
            "decisions_changed": 1,
            "results": [
                {
                    "trace_id": "t",
                    "decision_changed": True,
                    "original_decision": "allow",
                    "new_decision": "review",
                }
            ],
        }
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = replay_json
        post_resp.raise_for_status = MagicMock()

        http = AsyncMock()
        http.post = AsyncMock(return_value=post_resp)

        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "*"
            mock_settings.decision_api_url = "http://decision:8000"
            mock_settings.upstream_api_key = ""
            out = await tool_run_replay_ab_comparison(http, "t1", "a1", rules_a, rules_b, limit=50)

        assert http.post.call_count == 2
        assert out["comparison"]["decisions_changed_a"] == 1
        assert out["comparison"]["decisions_changed_b"] == 1

    @pytest.mark.asyncio
    async def test_ab_sends_trace_ids_for_paired_replay(self):
        rules_a = [
            {"id": "r1", "when": [{"field": "amount", "op": "gte", "value": 1}], "score_delta": 1}
        ]
        rules_b = [
            {"id": "r2", "when": [{"field": "amount", "op": "gte", "value": 2}], "score_delta": 2}
        ]
        tid = "12345678-1234-1234-1234-123456789abc"
        replay_json = {
            "tenant_id": "t1",
            "events_evaluated": 1,
            "decisions_changed": 0,
            "missing_trace_ids": [],
            "results": [
                {
                    "trace_id": tid,
                    "decision_changed": False,
                    "original_decision": "allow",
                    "new_decision": "allow",
                },
            ],
        }
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = replay_json
        http = AsyncMock()
        http.post = AsyncMock(return_value=post_resp)

        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "*"
            mock_settings.decision_api_url = "http://decision:8000"
            mock_settings.upstream_api_key = ""
            out = await tool_run_replay_ab_comparison(
                http, "t1", "a1", rules_a, rules_b, limit=50, trace_ids=[tid]
            )

        body = http.post.call_args_list[0].kwargs["json"]
        assert body["trace_ids"] == [tid]
        assert out.get("trace_ids_mode") is True
        assert out["comparison"].get("paired_traces") == 1


class TestOfflineMode:
    @pytest.mark.asyncio
    async def test_llm_loop_returns_offline_message(self):
        from investigation_agent.main import _llm_tool_loop

        http = AsyncMock()
        with patch("investigation_agent.main.settings") as mock_settings:
            mock_settings.openai_api_key = ""
            reply, tool_calls, usage, rounds = await _llm_tool_loop(
                http,
                "system prompt",
                [{"role": "user", "content": "hello"}],
                "t1",
                "analyst1",
                TOOL_DEFINITIONS,
            )

        assert "offline" in reply.lower()
        assert tool_calls == []
        assert usage == {}
        assert rounds == 0
