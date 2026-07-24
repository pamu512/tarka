"""Unit tests for the investigation agent — RBAC, tool dispatch, offline mode."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from investigation_agent.tools import (
    TOOL_DEFINITIONS,
    TOOL_DISPATCH,
    _analyst_allowed,
    tool_search_knowledge,
    tool_export_outcome_labeled_dataset,
    tool_get_case,
    tool_get_entity_tags,
    tool_ingest_labeled_rows,
    tool_list_cases,
    tool_run_replay_ab_comparison,
    tool_subgraph,
)
from investigation_agent.okf_retrieval import KnowledgeResult, KnowledgeRetrievalResult

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
            "subgraph_with_velocity",
            "export_outcome_labeled_dataset",
            "ingest_labeled_rows",
            "get_stored_labeled_dataset",
            "run_replay_ab_comparison",
            "screen_sanctions_pep",
            "summarize_adverse_media",
            "consolidate_entity_profile",
            "graph_risk_narrative",
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


class TestSearchKnowledgeOkf:
    @pytest.mark.asyncio
    async def test_search_knowledge_uses_authenticated_scope_and_returns_okf_fields(self):
        http = AsyncMock()
        registry = MagicMock()
        retrieval = KnowledgeRetrievalResult(
            results=(
                KnowledgeResult(
                    text="High Amount Rule\n\nTransactions above threshold require review.",
                    authority="shared_okf",
                    concept_id="rules/high-amount",
                    content_hash="a" * 64,
                    evidence_ids=("ev-high-amount",),
                    retrieval_path=("rules/high-amount",),
                    score=1.0,
                    stale=False,
                ),
            ),
            retrieval_mode="exact",
            conflicts=(),
            abstain=False,
            bundle_revision="bundle-rev-1",
        )

        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "*"
            mock_settings.copilot_knowledge_embeddings = False
            mock_settings.copilot_embedding_model = "embed"
            mock_settings.copilot_rag_keyword_weight = 0.35
            with patch(
                "investigation_agent.tools.knowledge_store.retrieve_knowledge_async",
                new=AsyncMock(return_value=retrieval),
            ) as retrieve:
                result = await tool_search_knowledge(
                    http,
                    tenant_id="trusted-tenant",
                    analyst_id="trusted-analyst",
                    query="high-amount",
                    limit=5,
                    okf_registry=registry,
                )

        retrieve.assert_awaited_once()
        kwargs = retrieve.await_args.kwargs
        assert kwargs["tenant_id"] == "trusted-tenant"
        assert kwargs["analyst_id"] == "trusted-analyst"
        assert "bundle_path" not in kwargs
        assert result["retrieval_mode"] == "exact"
        assert result["bundle_revision"] == "bundle-rev-1"
        assert result["abstain"] is False
        assert result["conflicts"] == []
        assert result["hits"][0]["concept_id"] == "rules/high-amount"
        assert result["hits"][0]["content_hash"] == "a" * 64
        assert result["hits"][0]["evidence_ids"] == ["ev-high-amount"]
        assert result["hits"][0]["retrieval_path"] == ["rules/high-amount"]
        assert result["hits"][0]["authority"] == "shared_okf"

    @pytest.mark.asyncio
    async def test_search_knowledge_preserves_legacy_rag_hit_fields_on_okf_fallback(self):
        http = AsyncMock()
        legacy_hit = {
            "doc_id": "doc-1",
            "title": "Legacy memo",
            "chunk_index": 0,
            "snippet": "Legacy memo body",
            "score": 0.42,
            "semantic_score": None,
            "keyword_hits": 2,
            "knowledge_kind": "memo",
            "content_hash": "memo-hash",
        }

        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "*"
            mock_settings.copilot_knowledge_embeddings = False
            mock_settings.copilot_embedding_model = "embed"
            mock_settings.copilot_rag_keyword_weight = 0.35
            with (
                patch(
                    "investigation_agent.tools.knowledge_store.retrieve_knowledge_async",
                    new=AsyncMock(side_effect=RuntimeError("secret bundle path /tmp/okf")),
                ),
                patch(
                    "investigation_agent.tools.knowledge_store.search_async",
                    new=AsyncMock(
                        return_value={
                            "hits": [legacy_hit],
                            "query": "legacy memo",
                            "retrieval_mode": "keyword",
                        }
                    ),
                ),
            ):
                result = await tool_search_knowledge(
                    http,
                    tenant_id="trusted-tenant",
                    analyst_id="trusted-analyst",
                    query="legacy memo",
                    limit=5,
                    okf_registry=MagicMock(),
                )

        assert result["hits"][0] == legacy_hit
        assert result["okf_unavailable"] is True
        assert result["abstain"] is True
        assert result["okf_error"] == "okf_unavailable"
        assert "/tmp/okf" not in str(result)

    @pytest.mark.asyncio
    async def test_search_knowledge_preserves_legacy_rag_metadata_on_successful_combined_retrieval(
        self,
    ):
        http = AsyncMock()
        raw_legacy_hit = {
            "doc_id": "doc-1",
            "title": "Legacy memo",
            "chunk_index": 3,
            "snippet": "Legacy memo body only.",
            "score": 0.71,
            "semantic_score": 0.77,
            "keyword_hits": 4,
            "knowledge_kind": "memo",
            "bundle_scope": "tenant",
            "source_uri": "memo://doc-1",
            "authority": 10,
        }
        retrieval = KnowledgeRetrievalResult(
            results=(
                KnowledgeResult(
                    text=raw_legacy_hit["snippet"],
                    authority="memo_rag",
                    concept_id=None,
                    content_hash="memo-hash",
                    evidence_ids=(),
                    retrieval_path=(),
                    score=raw_legacy_hit["score"],
                    stale=False,
                    metadata=raw_legacy_hit,
                ),
            ),
            retrieval_mode="exact+keyword",
            conflicts=(),
            abstain=False,
            bundle_revision="bundle-rev-1",
        )

        with patch("investigation_agent.tools.settings") as mock_settings:
            mock_settings.allowed_analysts = "*"
            mock_settings.copilot_knowledge_embeddings = False
            mock_settings.copilot_embedding_model = "embed"
            mock_settings.copilot_rag_keyword_weight = 0.35
            with patch(
                "investigation_agent.tools.knowledge_store.retrieve_knowledge_async",
                new=AsyncMock(return_value=retrieval),
            ):
                result = await tool_search_knowledge(
                    http,
                    tenant_id="trusted-tenant",
                    analyst_id="trusted-analyst",
                    query="legacy memo",
                    limit=5,
                    okf_registry=MagicMock(),
                )

        hit = result["hits"][0]
        for key, value in raw_legacy_hit.items():
            assert hit[key] == value
        assert hit["content_hash"] == "memo-hash"
        assert hit["authority_label"] == "memo_rag"

    def test_okf_abstain_lineage_is_recorded_for_strict_mode(self):
        from investigation_agent.main import (
            _apply_okf_strict_abstention,
            _knowledge_lineage_from_tool_calls,
        )

        tool_calls = [
            {
                "tool": "search_knowledge",
                "args": {"query": "unsupported policy"},
                "result": {
                    "hits": [
                        {
                            "concept_id": "rules/high-amount",
                            "evidence_ids": ["ev-high-amount"],
                        }
                    ],
                    "abstain": True,
                    "conflicts": ["shared_okf conflict for guidance/a.json: a != b"],
                    "bundle_revision": "bundle-rev-2",
                },
            }
        ]

        lineage = _knowledge_lineage_from_tool_calls(tool_calls)
        assert lineage["evidence_ids"] == []
        assert lineage["concept_ids"] == []
        assert lineage["okf_abstain"] is True
        assert lineage["conflicts"] == ["shared_okf conflict for guidance/a.json: a != b"]
        assert lineage["bundle_revision"] == "bundle-rev-2"

        reply, claims, refused = _apply_okf_strict_abstention(
            "The unsupported policy applies.",
            [{"text": "The unsupported policy applies.", "source": "tool"}],
            assurance_mode="strict",
            lineage=lineage,
        )

        assert refused is True
        assert "abstain" in reply.lower()
        assert claims == [{"text": reply, "source": "unknown"}]

    def test_abstaining_or_conflicting_search_results_do_not_authorize_exact_ids(self):
        from investigation_agent.main import _knowledge_lineage_from_tool_calls

        base_hit = {
            "concept_id": "rules/high-amount",
            "evidence_ids": ["ev-high-amount"],
        }
        for result in (
            {"hits": [base_hit], "abstain": True, "conflicts": []},
            {"hits": [base_hit], "abstain": False, "conflicts": ["conflict"]},
            {"hits": [base_hit], "okf_unavailable": True, "abstain": True},
            {"hits": [base_hit], "error": "tool_failed"},
        ):
            lineage = _knowledge_lineage_from_tool_calls(
                [{"tool": "search_knowledge", "result": result}]
            )
            assert lineage["concept_ids"] == []
            assert lineage["evidence_ids"] == []

    def test_okf_unavailable_lineage_abstains_in_strict_mode(self):
        from investigation_agent.main import (
            _apply_okf_strict_abstention,
            _knowledge_lineage_from_tool_calls,
        )

        tool_calls = [
            {
                "tool": "search_knowledge",
                "args": {"query": "legacy memo"},
                "result": {
                    "hits": [{"doc_id": "doc-1", "title": "Legacy memo"}],
                    "okf_unavailable": True,
                    "okf_error": "okf_unavailable",
                    "abstain": True,
                    "retrieval_mode": "keyword",
                },
            }
        ]

        lineage = _knowledge_lineage_from_tool_calls(tool_calls)
        assert lineage["okf_unavailable"] is True
        assert lineage["retrieval_fallback"] == "memo_rag"

        reply, claims, refused = _apply_okf_strict_abstention(
            "Memo fallback answer.",
            [{"text": "Memo fallback answer.", "source": "tool"}],
            assurance_mode="strict",
            lineage=lineage,
        )
        assert refused is True
        assert "abstain" in reply.lower()
        assert claims == [{"text": reply, "source": "unknown"}]

    def test_okf_claim_parser_preserves_exact_identifier_fields(self):
        from investigation_agent.main import _parse_tarka_claims_reply

        raw = (
            "High amount requires review.\n"
            'TARKA_CLAIMS_JSON={"claims":[{"text":"High amount requires review.",'
            '"source":"tool","concept_ids":["rules/high-amount"],'
            '"evidence_ids":["ev-high-amount"],"supporting_tool_call_indices":[0]}]}'
        )

        _, claims, warning = _parse_tarka_claims_reply(raw)

        assert warning is None
        assert claims == [
            {
                "text": "High amount requires review.",
                "source": "tool",
                "concept_ids": ["rules/high-amount"],
                "evidence_ids": ["ev-high-amount"],
                "supporting_tool_call_indices": [0],
            }
        ]

    def test_exact_id_grounding_rejects_fabricated_model_ids(self):
        from investigation_agent.main import _enforce_claim_exact_ids

        claims = [
            {
                "text": "The retrieved high amount rule applies.",
                "source": "tool",
                "concept_ids": ["rules/high-amount"],
                "evidence_ids": ["ev-high-amount"],
                "supporting_tool_call_indices": [0],
            },
            {
                "text": "The fabricated rule applies even though high-amount appears in text.",
                "source": "tool",
                "concept_ids": ["rules/fabricated"],
                "evidence_ids": ["ev-fabricated"],
                "supporting_tool_call_indices": [0],
            },
        ]
        tool_calls = [
            {
                "tool": "search_knowledge",
                "args": {"query": "high amount"},
                "result": {
                    "hits": [
                        {
                            "concept_id": "rules/high-amount",
                            "evidence_ids": ["ev-high-amount"],
                            "title": "High Amount Rule",
                            "snippet": "High amount transactions require review.",
                        }
                    ],
                    "abstain": False,
                    "conflicts": [],
                },
            }
        ]

        grounded, adjustments = _enforce_claim_exact_ids(claims, tool_calls)

        assert grounded[0]["source"] == "tool"
        assert grounded[0]["concept_ids"] == ["rules/high-amount"]
        assert grounded[1]["source"] == "unknown"
        assert grounded[1]["supported"] is False
        assert grounded[1]["concept_ids"] == ["rules/fabricated"]
        assert "unresolved_exact_citation_id" in adjustments

    def test_exact_id_grounding_is_claim_specific_across_multiple_queries(self):
        from investigation_agent.main import _enforce_claim_exact_ids

        tool_calls = [
            {
                "tool": "search_knowledge",
                "args": {"query": "high amount"},
                "result": {
                    "hits": [
                        {
                            "concept_id": "rules/high-amount",
                            "evidence_ids": ["ev-high"],
                            "title": "High Amount Rule",
                            "snippet": "High amount transactions require manual review.",
                        }
                    ],
                    "abstain": False,
                    "conflicts": [],
                },
            },
            {
                "tool": "search_knowledge",
                "args": {"query": "mule network"},
                "result": {
                    "hits": [
                        {
                            "concept_id": "typologies/mule-network",
                            "evidence_ids": ["ev-mule"],
                            "title": "Mule Network Typology",
                            "snippet": "Linked beneficiary accounts indicate mule-network activity.",
                        }
                    ],
                    "abstain": False,
                    "conflicts": [],
                },
            },
        ]
        claims = [
            {
                "text": "High amount transactions require manual review.",
                "source": "tool",
                "concept_ids": ["rules/high-amount"],
                "evidence_ids": ["ev-high"],
                "supporting_tool_call_indices": [0],
            },
            {
                "text": "High amount transactions require manual review.",
                "source": "tool",
                "concept_ids": ["typologies/mule-network"],
                "evidence_ids": ["ev-mule"],
                "supporting_tool_call_indices": [1],
            },
            {
                "text": "A fabricated policy requires manual review.",
                "source": "tool",
                "concept_ids": ["rules/fabricated"],
                "evidence_ids": ["ev-fabricated"],
                "supporting_tool_call_indices": [0],
            },
            {
                "text": "High amount transactions require manual review.",
                "source": "tool",
                "concept_ids": [
                    "rules/high-amount",
                    "typologies/mule-network",
                ],
                "evidence_ids": ["ev-high", "ev-mule"],
                "supporting_tool_call_indices": [0, 1],
            },
        ]

        grounded, adjustments = _enforce_claim_exact_ids(claims, tool_calls)

        assert grounded[0]["source"] == "tool"
        assert grounded[1]["source"] == "unknown"
        assert grounded[1]["supported"] is False
        assert grounded[2]["source"] == "unknown"
        assert grounded[2]["supported"] is False
        assert grounded[3]["source"] == "unknown"
        assert grounded[3]["supported"] is False
        assert "exact_citation_text_unsupported" in adjustments
        assert "unresolved_exact_citation_id" in adjustments

    def test_search_grounding_rejects_omitted_unrelated_and_fabricated_citations(self):
        from investigation_agent.main import _enforce_claim_exact_ids

        tool_calls = [
            {
                "tool": "search_knowledge",
                "result": {
                    "hits": [
                        {
                            "concept_id": "rules/high-amount",
                            "evidence_ids": ["ev-high"],
                            "title": "High Amount Rule",
                            "snippet": "High amount transactions require manual review.",
                        }
                    ],
                    "abstain": False,
                    "conflicts": [],
                },
            },
            {
                "tool": "search_knowledge",
                "result": {
                    "hits": [
                        {
                            "concept_id": "typologies/mule-network",
                            "evidence_ids": ["ev-mule"],
                            "title": "Mule Network",
                            "snippet": "Linked beneficiary accounts indicate mule activity.",
                        }
                    ],
                    "abstain": False,
                    "conflicts": [],
                },
            },
        ]
        claims = [
            {
                "text": "High amount transactions require manual review.",
                "source": "tool",
            },
            {
                "text": "High amount transactions require manual review.",
                "source": "tool",
                "concept_ids": ["typologies/mule-network"],
                "evidence_ids": ["ev-mule"],
                "supporting_tool_call_indices": [0],
            },
            {
                "text": "High amount transactions require manual review.",
                "source": "tool",
                "concept_ids": ["rules/fabricated"],
                "evidence_ids": ["ev-fabricated"],
                "supporting_tool_call_indices": [0],
            },
            {
                "text": "High amount transactions require manual review.",
                "source": "tool",
                "concept_ids": ["rules/high-amount"],
                "evidence_ids": ["ev-high"],
                "supporting_tool_call_indices": [0],
            },
        ]

        grounded, adjustments = _enforce_claim_exact_ids(claims, tool_calls)

        assert [claim["source"] for claim in grounded] == [
            "unknown",
            "unknown",
            "unknown",
            "tool",
        ]
        assert all(claim.get("supported") is False for claim in grounded[:3])
        assert "search_knowledge_citation_omitted" in adjustments
        assert "unresolved_exact_citation_id" in adjustments

    def test_all_tool_claims_require_successful_selected_call_indices(self):
        from investigation_agent.main import _enforce_claim_exact_ids

        tool_calls = [
            {"tool": "get_case", "result": {"case": {"id": "case-1", "status": "open"}}},
            {"tool": "list_cases", "result": {"items": [{"id": "case-2"}]}},
            {"tool": "get_decision_audit", "result": {"error": "upstream_failed"}},
        ]
        claims = [
            {
                "text": "Case case-1 is open.",
                "source": "tool",
                "supporting_tool_call_indices": [0],
            },
            {"text": "A case was fetched.", "source": "tool"},
            {
                "text": "The failed audit supports this.",
                "source": "tool",
                "supporting_tool_call_indices": [2],
            },
            {
                "text": "Queue includes case-2.",
                "source": "tool",
                "supporting_tool_call_indices": [1],
            },
        ]

        grounded, adjustments = _enforce_claim_exact_ids(claims, tool_calls)

        assert [claim["source"] for claim in grounded] == [
            "tool",
            "unknown",
            "unknown",
            "tool",
        ]
        assert grounded[1]["supported"] is False
        assert grounded[2]["supported"] is False
        assert adjustments.count("tool_call_binding_invalid") == 2

    @pytest.mark.parametrize("assurance_mode", ["standard", "strict"])
    def test_exact_citation_violation_withholds_narrative_in_all_modes(self, assurance_mode):
        from investigation_agent.main import _apply_grounding_abstention

        reply, claims, refused = _apply_grounding_abstention(
            "Fabricated claim that must not remain visible.",
            [
                {
                    "text": "Fabricated claim that must not remain visible.",
                    "source": "unknown",
                    "supported": False,
                }
            ],
            adjustments=["unresolved_exact_citation_id"],
            assurance_mode=assurance_mode,
        )

        assert refused is True
        assert "Fabricated claim" not in reply
        assert "withheld" in reply.lower() or "abstain" in reply.lower()
        assert claims == [{"text": reply, "source": "unknown", "supported": False}]

    def test_okf_claims_prompt_schema_requests_exact_ids_without_invention(self):
        from investigation_agent.personas import (
            DEFAULT_COPILOT_PERSONA,
            build_copilot_system_prompt,
        )

        prompt = build_copilot_system_prompt(DEFAULT_COPILOT_PERSONA)

        assert "concept_ids" in prompt
        assert "evidence_ids" in prompt
        assert "supporting_tool_call_indices" in prompt
        assert "do not invent" in prompt.lower()


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
