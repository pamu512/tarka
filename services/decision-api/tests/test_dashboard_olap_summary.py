"""Dashboard OLAP summary: timezone windows, DuckDB aggregates, cache key stability."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from analytics.dashboards import (
    dashboard_cache_key,
    fetch_dashboard_aggregates_sync,
    parse_dashboard_period,
)
from analytics.engine import DuckDBEngine


def test_parse_dashboard_period_midnight_in_timezone() -> None:
    utc_start, utc_end = parse_dashboard_period(
        "2024-06-10", "2024-06-10", "America/New_York"
    )
    assert utc_start == "2024-06-10 04:00:00"
    assert utc_end == "2024-06-11 04:00:00"


def test_dashboard_cache_key_includes_table() -> None:
    k1 = dashboard_cache_key(
        "t1", "2024-01-01", "2024-01-02", "UTC", "duckdb", table="fraud_decisions"
    )
    k2 = dashboard_cache_key(
        "t1", "2024-01-01", "2024-01-02", "UTC", "duckdb", table="other"
    )
    assert k1 != k2
    assert "fraud_decisions" in k1


def test_fetch_dashboard_aggregates_duckdb() -> None:
    p = Path(tempfile.gettempdir()) / "tarka-dashboard-olap-test.duckdb"
    p.unlink(missing_ok=True)
    eng = DuckDBEngine(p)
    try:
        eng._conn.execute(
            """
            INSERT INTO fraud_decisions (
              tenant_id, entity_id, created_at, trace_id, decision, score, payload_json, rule_hits_json
            ) VALUES
            ('acme', 'e1', TIMESTAMP '2025-01-10 12:00:00', 'a1', 'allow', 0.1,
             '{"amount": 100, "impossible_travel_risk": 0.1}', '["rule_a"]'),
            ('acme', 'e1', TIMESTAMP '2025-01-10 13:00:00', 'a2', 'deny', 0.9,
             '{"amount": 50, "impossible_travel_risk": 0.2}', '["rule_a","rule_b"]'),
            ('acme', 'e2', TIMESTAMP '2025-01-10 14:00:00', 'a3', 'review', 0.5,
             '{"payload": {"amount": 25}}', '["rule_b"]'),
            ('acme', 'e_geo', TIMESTAMP '2025-01-10 15:00:00', 'a4', 'allow', 0.2,
             '{"location_meta": {"impossible_travel_risk": 0.88}}', '[]'),
            ('acme', 'e_geo', TIMESTAMP '2025-01-10 16:00:00', 'a5', 'allow', 0.2,
             '{"location_meta": {"impossible_travel_risk": 0.9}}', '[]')
            """
        )
        out = fetch_dashboard_aggregates_sync(
            eng,
            "fraud_decisions",
            "acme",
            "2025-01-10 00:00:00",
            "2025-01-11 00:00:00",
        )
        assert out["total_transaction_volume"] == pytest.approx(175.0)
        assert out["total_events"] == 5
        assert out["blocked_events"] == 2
        assert out["block_rate"] == pytest.approx(0.4)
        rules = {r["rule_id"]: int(r["hits"]) for r in out["top_triggered_rules"]}
        assert rules.get("rule_a") == 2
        assert rules.get("rule_b") == 2
        geo = out["geo_velocity_spikes"]
        assert len(geo) == 1
        assert geo[0]["entity_id"] == "e_geo"
        assert float(geo[0]["peak_risk"]) >= 0.88
        assert int(geo[0]["event_count"]) == 2
    finally:
        eng.close()
        p.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_dashboard_summary_endpoint_uses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("tarka_core.cache")
    pytest.importorskip("httpx")
    from httpx import ASGITransport, AsyncClient

    from decision_api.deps import get_kv_cache
    from decision_api.main import app
    from tarka_core.cache import LocalDictCache

    monkeypatch.setenv("API_KEYS", "dash-test-key")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")

    p = Path(tempfile.gettempdir()) / "tarka-dashboard-api-test.duckdb"
    p.unlink(missing_ok=True)
    eng = DuckDBEngine(p)
    eng._conn.execute(
        """
        INSERT INTO fraud_decisions (
          tenant_id, entity_id, created_at, trace_id, decision, score, payload_json, rule_hits_json
        ) VALUES
        ('t1', 'x', TIMESTAMP '2025-02-01 10:00:00', 'z', 'allow', 0.0, '{"amount": 1}', '["r1"]')
        """
    )

    prev = getattr(app.state, "analytics_engine", None)
    app.state.analytics_engine = eng
    kv = LocalDictCache()
    calls: list[int] = []

    from decision_api import analytics_dashboards as ad

    real_fetch = fetch_dashboard_aggregates_sync

    def wrapped(*a: object, **kw: object) -> dict:
        calls.append(1)
        return real_fetch(*a, **kw)  # type: ignore[misc]

    monkeypatch.setattr(ad, "fetch_dashboard_aggregates_sync", wrapped)
    app.dependency_overrides[get_kv_cache] = lambda: kv

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            q = {
                "tenant_id": "t1",
                "period_start": "2025-02-01",
                "period_end": "2025-02-01",
                "timezone": "UTC",
            }
            r1 = await client.get(
                "/v1/analytics/dashboards/summary",
                params=q,
                headers={"x-api-key": "dash-test-key"},
            )
            assert r1.status_code == 200, r1.text
            body1 = r1.json()
            assert body1["total_events"] == 1
            assert body1["utc_window_start"].startswith("2025-02-01")

            r2 = await client.get(
                "/v1/analytics/dashboards/summary",
                params=q,
                headers={"x-api-key": "dash-test-key"},
            )
            assert r2.status_code == 200
            assert r2.json() == body1
        assert len(calls) == 1

        raw = await kv.get(
            dashboard_cache_key(
                "t1",
                "2025-02-01",
                "2025-02-01",
                "UTC",
                "duckdb",
                table="fraud_decisions",
            )
        )
        assert raw is not None
        cached = json.loads(raw)
        assert cached["total_events"] == 1
    finally:
        app.dependency_overrides.pop(get_kv_cache, None)
        app.state.analytics_engine = prev
        eng.close()
        p.unlink(missing_ok=True)
