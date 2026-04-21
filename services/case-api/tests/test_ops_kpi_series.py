"""Marble #57: KPI time-series export, median handling regression guards."""

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from case_api.ops_kpi_series import (
    build_bucket_payloads,
    build_time_buckets,
    median_float,
)
from case_api.workflow import is_sla_breached_at
from fastapi.testclient import TestClient


class TestMedianFloat:
    def test_empty(self):
        assert median_float([]) is None

    def test_odd(self):
        assert median_float([30.0, 10.0, 20.0]) == 20.0

    def test_even(self):
        assert median_float([10.0, 20.0, 30.0, 40.0]) == 25.0

    def test_single(self):
        assert median_float([42.0]) == 42.0


class TestBuildTimeBuckets:
    def test_daily_order_and_width(self):
        anchor = datetime(2026, 4, 20, 15, 30, tzinfo=timezone.utc)
        buckets = build_time_buckets(granularity="daily", periods=3, anchor=anchor)
        assert len(buckets) == 3
        assert buckets[0][0] == datetime(2026, 4, 18, tzinfo=timezone.utc)
        assert buckets[0][1] == datetime(2026, 4, 19, tzinfo=timezone.utc)
        assert buckets[2][0] == datetime(2026, 4, 20, tzinfo=timezone.utc)
        assert buckets[2][1] == datetime(2026, 4, 21, tzinfo=timezone.utc)

    def test_weekly_starts_monday(self):
        anchor = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)  # Monday
        buckets = build_time_buckets(granularity="weekly", periods=2, anchor=anchor)
        assert buckets[0][0].weekday() == 0
        assert buckets[0][1] - buckets[0][0] == timedelta(weeks=1)


class TestBuildBucketPayloads:
    def test_median_handling_closed_same_bucket(self):
        day0 = datetime(2026, 1, 10, tzinfo=timezone.utc)
        buckets = [(day0, day0 + timedelta(days=1))]
        cases = [
            SimpleNamespace(
                status="closed",
                priority="medium",
                created_at=day0 + timedelta(hours=1),
                updated_at=day0 + timedelta(hours=11),
                sla_hours_override=None,
            ),
            SimpleNamespace(
                status="resolved",
                priority="medium",
                created_at=day0 + timedelta(hours=2),
                updated_at=day0 + timedelta(hours=22),
                sla_hours_override=None,
            ),
            SimpleNamespace(
                status="closed",
                priority="medium",
                created_at=day0 + timedelta(hours=3),
                updated_at=day0 + timedelta(hours=15),
                sla_hours_override=None,
            ),
        ]
        out = build_bucket_payloads(cases, buckets)[0]
        assert out["cases_closed"] == 3
        assert out["median_handling_hours_closed"] == pytest.approx(12.0)

    def test_sla_breach_count_at_period_end(self):
        day0 = datetime(2026, 1, 10, tzinfo=timezone.utc)
        buckets = [(day0, day0 + timedelta(days=1))]
        created = day0 + timedelta(hours=1)
        cases = [
            SimpleNamespace(
                status="open",
                priority="medium",
                created_at=created,
                updated_at=day0 + timedelta(hours=2),
                sla_hours_override=None,
            ),
        ]
        out = build_bucket_payloads(cases, buckets)[0]
        assert out["sla_breached_open_or_investigating_at_period_end"] == 0

        cases_breach = [
            SimpleNamespace(
                status="open",
                priority="medium",
                created_at=day0 - timedelta(days=5),
                updated_at=day0 + timedelta(hours=2),
                sla_hours_override=None,
            ),
        ]
        out2 = build_bucket_payloads(cases_breach, buckets)[0]
        assert out2["sla_breached_open_or_investigating_at_period_end"] >= 1


class TestIsSlaBreachedAt:
    def test_not_breached_as_of_before_deadline(self):
        created = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        as_of = created + timedelta(hours=12)
        assert is_sla_breached_at("medium", created, as_of=as_of) is False

    def test_breached_as_of_after_deadline(self):
        created = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        as_of = created + timedelta(hours=48)
        assert is_sla_breached_at("medium", created, as_of=as_of) is True


def _api_headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys, "tests/conftest.py should set API_KEYS"
    return {"X-API-Key": keys[0]}


def test_kpi_series_http_smoke():
    from case_api.main import app

    with TestClient(app) as client:
        r = client.get(
            "/v1/cases/ops/kpi-series",
            params={
                "tenant_id": "kpi-tenant-smoke",
                "granularity": "daily",
                "periods": 2,
                "as_of": "2026-04-20T12:00:00+00:00",
            },
            headers=_api_headers(),
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["schema"] == "tarka.case_kpi_series/v1"
    assert data["tenant_id"] == "kpi-tenant-smoke"
    assert len(data["buckets"]) == 2
    assert "median_handling_hours_closed_window" in data["summary"]
