"""Dashboards router (moved from decision-api; prune plan v7 item 3.2).

Pins the honest-offline contract: the 503 reason codes and message bodies carried
over verbatim, plus the happy path against a fake engine + in-process cache.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_SRC = Path(__file__).resolve().parents[1] / "src"
for candidate in (_SRC, *sys.path):
    if (Path(candidate) / "analytics_sink" / "dashboards.py").exists():
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
        break

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from analytics_sink.dashboards import router  # noqa: E402
from tarka_core.cache import LocalDictCache  # noqa: E402


class _FakeEngine:
    backend = "duckdb"

    def get_kpi(self, tenant_id, table, *, max_execution_seconds):
        return {"event_count": 7}

    def fetch_dashboard_aggregates_sync(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("summary path uses module-level fetch fn")


def _client(*, engine_on: bool = True, table: str = "fraud_decisions"):
    app = FastAPI()
    app.include_router(router)
    app.state.analytics_engine = _FakeEngine() if engine_on else None
    app.state.kv_cache = LocalDictCache()
    app.state.settings_table = table
    return TestClient(app, raise_server_exceptions=False)


class TestDashboardsRouter(unittest.TestCase):
    def test_kpis_happy_path_and_cache(self) -> None:
        with _client() as client:
            r1 = client.get("/v1/analytics/dashboards/kpis", params={"tenant_id": "t1"})
            self.assertEqual(r1.status_code, 200)
            body = r1.json()
            self.assertEqual(body["event_count"], 7)
            self.assertEqual(body["source"], "duckdb")
            r2 = client.get("/v1/analytics/dashboards/kpis", params={"tenant_id": "t1"})
            self.assertEqual(r2.json(), body)  # served from cache

    def test_engine_offline_503_body(self) -> None:
        with _client(engine_on=False) as client:
            r = client.get("/v1/analytics/dashboards/kpis", params={"tenant_id": "t1"})
            self.assertEqual(r.status_code, 503)
            self.assertEqual(r.json()["detail"]["reason_code"], "ANALYTICS_ENGINE_OFFLINE")

    def test_config_invalid_table_503_body(self) -> None:
        from analytics_sink import dashboards as mod

        original = mod.settings.clickhouse_analytics_events_table
        mod.settings.clickhouse_analytics_events_table = "not_allowed_table"
        try:
            with _client() as client:
                r = client.get("/v1/analytics/dashboards/kpis", params={"tenant_id": "t1"})
                self.assertEqual(r.status_code, 503)
                detail = r.json()["detail"]
                self.assertEqual(detail["reason_code"], "ANALYTICS_CONFIG_INVALID")
                self.assertIn("NL_SQL_ALLOWED_TABLES", detail["message"])
        finally:
            mod.settings.clickhouse_analytics_events_table = original

    def test_summary_engine_offline_503_body(self) -> None:
        class _BoomEngine(_FakeEngine):
            def get_kpi(self, *a, **k):  # pragma: no cover
                raise AssertionError("unused")

        import analytics_sink.dashboards as mod

        original = mod.fetch_dashboard_aggregates_sync
        mod.fetch_dashboard_aggregates_sync = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("connection refused")
        )
        try:
            app = FastAPI()
            app.include_router(router)
            app.state.analytics_engine = _BoomEngine()
            app.state.kv_cache = LocalDictCache()
            with TestClient(app, raise_server_exceptions=False) as client:
                r = client.get(
                    "/v1/analytics/dashboards/summary",
                    params={
                        "tenant_id": "t1",
                        "period_start": "2026-11-01",
                        "period_end": "2026-11-02",
                        "timezone": "UTC",
                    },
                )
                self.assertEqual(r.status_code, 503)
                detail = r.json()["detail"]
                self.assertEqual(detail["reason_code"], "ANALYTICS_ENGINE_OFFLINE")
                self.assertEqual(
                    detail["message"],
                    "Dashboard summary query failed or exceeded execution budget.",
                )
        finally:
            mod.fetch_dashboard_aggregates_sync = original


if __name__ == "__main__":
    unittest.main()
