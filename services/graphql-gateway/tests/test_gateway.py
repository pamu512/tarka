"""Unit tests for the GraphQL gateway — schema resolvers with mocked backends."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from graphql_gateway.schema import _parse_case, _parse_dt, schema

# ---------- _parse_dt ----------


class TestParseDt:
    def test_valid_iso_string(self):
        dt = _parse_dt("2025-01-15T10:30:00")
        assert dt is not None
        assert dt.hour == 10

    def test_none_returns_none(self):
        assert _parse_dt(None) is None

    def test_invalid_string_returns_none(self):
        assert _parse_dt("not-a-date") is None


# ---------- _parse_case ----------


class TestParseCase:
    def test_parse_case_full(self):
        data = {
            "id": "abc-123",
            "tenant_id": "t1",
            "title": "Suspicious login",
            "status": "open",
            "entity_id": "user-1",
            "trace_id": "tr-1",
            "priority": "high",
            "assigned_team": "fraud-ops",
            "labels": ["urgent"],
            "created_at": "2025-06-01T12:00:00",
            "updated_at": "2025-06-02T14:00:00",
        }
        case = _parse_case(data)
        assert case.id == "abc-123"
        assert case.title == "Suspicious login"
        assert case.priority == "high"
        assert case.labels == ["urgent"]

    def test_parse_case_minimal(self):
        data = {
            "id": "x",
            "tenant_id": "t1",
            "title": "Test",
            "status": "open",
            "entity_id": "e1",
            "trace_id": "tr1",
        }
        case = _parse_case(data)
        assert case.priority == "medium"
        assert case.assigned_team is None
        assert case.labels == []


# ---------- GraphQL query/mutation execution ----------


def _make_http_mock(responses: dict):
    """Create a mock httpx.AsyncClient that returns predefined responses by URL pattern."""

    async def _mock_request(method, url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = ""
        for pattern, data in responses.items():
            if pattern in str(url):
                resp.json.return_value = data
                return resp
        resp.status_code = 404
        resp.text = "Not found"
        return resp

    mock = AsyncMock()
    mock.get = AsyncMock(side_effect=lambda url, **kw: _mock_request("GET", url, **kw))
    mock.post = AsyncMock(side_effect=lambda url, **kw: _mock_request("POST", url, **kw))
    return mock


class TestGraphQLQueries:
    @pytest.mark.asyncio
    async def test_cases_query(self):
        http = _make_http_mock(
            {
                "/v1/cases": {
                    "items": [
                        {
                            "id": "c1",
                            "tenant_id": "t1",
                            "title": "Test case",
                            "status": "open",
                            "entity_id": "e1",
                            "trace_id": "tr1",
                            "priority": "high",
                            "labels": [],
                            "created_at": None,
                            "updated_at": None,
                        }
                    ]
                }
            }
        )

        result = await schema.execute(
            """
            query {
                cases(tenantId: "t1") {
                    id
                    title
                    status
                }
            }
            """,
            context_value={"http_client": http},
        )

        assert result.errors is None
        assert len(result.data["cases"]) == 1
        assert result.data["cases"][0]["title"] == "Test case"

    @pytest.mark.asyncio
    async def test_case_by_id_query(self):
        http = _make_http_mock(
            {
                "/v1/cases/c1": {
                    "id": "c1",
                    "tenant_id": "t1",
                    "title": "Single case",
                    "status": "investigating",
                    "entity_id": "e1",
                    "trace_id": "tr1",
                    "priority": "medium",
                    "labels": ["fraud"],
                    "created_at": None,
                    "updated_at": None,
                }
            }
        )

        result = await schema.execute(
            """
            query {
                case(id: "c1", tenantId: "t1") {
                    id
                    title
                    status
                    labels
                }
            }
            """,
            context_value={"http_client": http},
        )

        assert result.errors is None
        assert result.data["case"]["title"] == "Single case"
        assert result.data["case"]["labels"] == ["fraud"]

    @pytest.mark.asyncio
    async def test_subgraph_query(self):
        http = _make_http_mock(
            {
                "/v1/subgraph": {
                    "nodes": [
                        {"id": "n1", "labels": ["User"], "properties": {"name": "Alice"}},
                    ],
                    "edges": [
                        {"from_id": "n1", "to_id": "n2", "type": "PAYS", "properties": {}},
                    ],
                }
            }
        )

        result = await schema.execute(
            """
            query {
                subgraph(tenantId: "t1", entityId: "e1") {
                    nodes { id labels }
                    edges { fromId toId type }
                }
            }
            """,
            context_value={"http_client": http},
        )

        assert result.errors is None
        assert len(result.data["subgraph"]["nodes"]) == 1
        assert result.data["subgraph"]["edges"][0]["type"] == "PAYS"

    @pytest.mark.asyncio
    async def test_entity_tags_query(self):
        http = _make_http_mock({"/v1/entities/e1/tags": {"tags": ["suspicious", "vpn"]}})

        result = await schema.execute(
            """
            query {
                entityTags(tenantId: "t1", entityId: "e1")
            }
            """,
            context_value={"http_client": http},
        )

        assert result.errors is None
        assert "suspicious" in result.data["entityTags"]


class TestGraphQLMutations:
    @pytest.mark.asyncio
    async def test_evaluate_mutation(self):
        http = _make_http_mock(
            {
                "/v1/decisions/evaluate": {
                    "trace_id": "tr-42",
                    "decision": "deny",
                    "score": 88.5,
                    "tags": ["high_risk"],
                    "rule_hits": ["r1"],
                    "reasons": ["high amount"],
                    "ml_score": 75.0,
                    "recommended_action": "manual_review",
                    "inference_context": {
                        "schema_version": "3",
                        "confidence_tier": "high",
                    },
                }
            }
        )

        result = await schema.execute(
            """
            mutation {
                evaluate(input: {tenantId: "t1", eventType: "payment", entityId: "e1"}) {
                    traceId
                    decision
                    score
                    tags
                    recommendedAction
                    inferenceContext
                }
            }
            """,
            context_value={"http_client": http},
        )

        assert result.errors is None
        assert result.data["evaluate"]["decision"] == "deny"
        assert result.data["evaluate"]["score"] == 88.5
        assert result.data["evaluate"]["recommendedAction"] == "manual_review"
        assert result.data["evaluate"]["inferenceContext"]["confidence_tier"] == "high"

    @pytest.mark.asyncio
    async def test_create_case_mutation(self):
        http = _make_http_mock(
            {
                "/v1/cases": {
                    "id": "new-case-1",
                    "tenant_id": "t1",
                    "title": "New case",
                    "status": "open",
                    "entity_id": "e1",
                    "trace_id": "tr1",
                    "priority": "high",
                    "labels": [],
                    "created_at": None,
                    "updated_at": None,
                }
            }
        )

        result = await schema.execute(
            """
            mutation {
                createCase(input: {tenantId: "t1", title: "New case", entityId: "e1", traceId: "tr1", priority: "high"}) {
                    id
                    title
                    status
                }
            }
            """,
            context_value={"http_client": http},
        )

        assert result.errors is None
        assert result.data["createCase"]["title"] == "New case"
