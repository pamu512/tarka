"""Async OSINT Redis lag budget (CQRS read path)."""

from datetime import UTC, datetime, timedelta

import pytest

from decision_api.async_enrich_freshness import evaluate_async_enrich_freshness
from decision_api.async_osint_redis import merge_cached_async_osint
from decision_api.degraded_decision_metrics import record_degraded_decision_metrics


def test_fresh_blob_ok() -> None:
    recent = (
        (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    )
    r = evaluate_async_enrich_freshness(
        {"updated_at": recent},
        max_age_minutes=60,
        tenant_id="t1",
        entity_id="e1",
    )
    assert r.action == "ok"
    assert r.age_minutes is not None and r.age_minutes < 60


def test_stale_blob() -> None:
    old = (datetime.now(UTC) - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    r = evaluate_async_enrich_freshness(
        {"updated_at": old},
        max_age_minutes=60,
        tenant_id="t1",
        entity_id="e1",
    )
    assert r.action == "stale"
    assert r.age_minutes is not None and r.age_minutes > 60


def test_disabled_when_max_age_zero() -> None:
    old = (datetime.now(UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    r = evaluate_async_enrich_freshness({"updated_at": old}, max_age_minutes=0)
    assert r.action == "ok"


def test_missing_ts() -> None:
    r = evaluate_async_enrich_freshness({"osint": {}}, max_age_minutes=60)
    assert r.action == "missing_ts"


@pytest.mark.asyncio
async def test_merge_stale_tags_and_still_applies_features() -> None:
    old = (datetime.now(UTC) - timedelta(hours=4)).isoformat().replace("+00:00", "Z")
    blob = {
        "updated_at": old,
        "osint": {"composite_risk_score": 0.42},
    }
    import json

    class _FakeRedis:
        async def get(self, _key: str) -> str:
            return json.dumps(blob)

    features: dict = {}
    degrade: list[str] = []
    metrics: list[str] = []
    await merge_cached_async_osint(
        _FakeRedis(),
        "t1",
        "e1",
        features,
        degrade_tags=degrade,
        max_age_minutes=60,
        metrics_inc=metrics.append,
    )
    assert "async_enrich:stale" in degrade
    assert "tarka_async_enrich_stale_total" in metrics
    assert features.get("osint_composite_risk") == 0.42


def test_degraded_metrics_maps_async_enrich_stale() -> None:
    seen: list[str] = []
    emitted = record_degraded_decision_metrics(
        ["async_enrich:stale"],
        metrics_inc=seen.append,
    )
    assert emitted == ["async_enrich_stale"]
    assert "tarka_degraded_decision_async_enrich_stale_total" in seen
