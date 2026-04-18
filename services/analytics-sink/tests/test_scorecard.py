from unittest.mock import MagicMock, patch

from analytics_sink.main import app
from fastapi.testclient import TestClient


class _FakeQueryResult:
    def __init__(self, column_names, rows):
        self.column_names = column_names
        self.result_rows = rows


def _mock_scorecard_queries(mock_ch):
    # Decision aggregates
    decision_rows = [
        ("deny", 30, 80.0, 60.0, 100.0),
        ("review", 20, 55.0, 40.0, 70.0),
        ("allow", 50, 10.0, 0.0, 30.0),
    ]
    rules_rows = [
        ("velocity_high_1h", 40),
        ("amount_stress", 10),
    ]

    def _query(sql: str):
        sql_l = sql.lower()
        if "group by decision" in sql_l:
            return _FakeQueryResult(
                ["decision", "event_count", "avg_score", "min_score", "max_score"],
                decision_rows,
            )
        if "arrayjoin(rule_hits)" in sql_l:
            return _FakeQueryResult(["rule_id", "hit_count"], rules_rows)
        raise AssertionError(f"unexpected query: {sql}")

    mock_ch.query.side_effect = _query


def test_decision_scorecard_shape_and_metrics():
    mock_ch = MagicMock()
    _mock_scorecard_queries(mock_ch)

    with patch("analytics_sink.main._ch_client", mock_ch):
        with patch("analytics_sink.main._init_clickhouse"):
            with patch("analytics_sink.main.asyncio.create_task"):
                with TestClient(app) as client:
                    r = client.get("/v1/analytics/scorecard", params={"tenant_id": "t1", "days": 7})

    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == "t1"
    assert data["window_days"] == 7
    assert data["total_events"] == 100
    # 30 deny out of 100
    assert data["deny_rate_pct"] == 30.0
    assert isinstance(data["per_decision"], list) and len(data["per_decision"]) == 3
    deny_row = next(d for d in data["per_decision"] if d["decision"] == "deny")
    assert deny_row["event_count"] == 30
    assert deny_row["event_pct"] == 30.0
    assert isinstance(data["top_rule_hits"], list)
    assert data["top_rule_hits"][0]["rule_id"] == "velocity_high_1h"
