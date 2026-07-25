from unittest.mock import MagicMock, patch

from analytics_sink.main import app
from fastapi.testclient import TestClient


class _FakeQueryResult:
    def __init__(self, column_names, rows):
        self.column_names = column_names
        self.result_rows = rows


def test_query_decisions_uses_bound_parameters():
    mock_ch = MagicMock()
    mock_ch.query.return_value = _FakeQueryResult(["trace_id"], [("tr1",)])
    with patch("analytics_sink.main._ch_client", mock_ch):
        with patch("analytics_sink.main._init_clickhouse"):
            with patch("analytics_sink.main.asyncio.create_task"):
                with patch("analytics_sink.main._get_api_keys", return_value=frozenset({"k1"})):
                    with TestClient(app) as client:
                        r = client.get(
                            "/v1/analytics/decisions",
                            params={
                                "tenant_id": "tenant-x",
                                "decision": "deny' OR 1=1 --",
                                "entity_id": "ent-123",
                                "days": 7,
                                "limit": 25,
                            },
                            headers={"x-api-key": "k1"},
                        )
    assert r.status_code == 200
    assert mock_ch.query.call_count == 1
    q = mock_ch.query.call_args.args[0]
    params = mock_ch.query.call_args.kwargs.get("parameters") or {}
    assert "%(tenant_id)s" in q
    assert "%(decision)s" in q
    assert "%(entity_id)s" in q
    assert params["decision"] == "deny' OR 1=1 --"
    assert params["tenant_id"] == "tenant-x"
    assert params["entity_id"] == "ent-123"
    assert params["days"] == 7
    assert params["limit"] == 25
