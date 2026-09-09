"""W5 L2 empty URL, W6 ring job, OPT vendor_score."""

from __future__ import annotations

import pytest

from decision_api.feature_l2 import (
    get_features,
    holdout_split,
    resolve_feature_source,
    serve_features,
    upsert_feature,
)
from decision_api.ring_job import (
    JOB_REQUEST_SCHEMA,
    run_ring_job,
    validate_ring_request,
)
from decision_api.vendor_score import fetch_vendor_score, vendor_score_url


def test_empty_feature_store_url_not_l2(monkeypatch) -> None:
    monkeypatch.delenv("FEATURE_STORE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("TARKA_REDIS_URL", raising=False)
    assert resolve_feature_source(redis_url="") == "raw"
    monkeypatch.setenv("FEATURE_STORE_URL", "")
    assert resolve_feature_source(redis_url="") == "raw"
    monkeypatch.setenv("FEATURE_STORE_URL", "   ")
    assert resolve_feature_source(redis_url="") == "raw"
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs")
    assert resolve_feature_source() == "l2"


def test_empty_feature_store_url_with_redis_is_l1(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("TARKA_REDIS_URL", raising=False)
    assert resolve_feature_source(redis_url="redis://localhost:6379/0") == "l1"
    monkeypatch.setenv("FEATURE_STORE_URL", "   ")
    assert resolve_feature_source(redis_url="redis://127.0.0.1:6379/1") == "l1"


@pytest.mark.asyncio
async def test_serve_features_empty_url_is_l2_off(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("TARKA_REDIS_URL", raising=False)
    out = await serve_features("user", "e1", tenant_id="t1")
    assert out["l2"] == "off"
    assert out["feature_source"] in {"l1", "raw"}
    assert out["feature_source"] != "l2"


def test_pit_as_of() -> None:
    upsert_feature(
        tenant_id="t1",
        entity_type="user",
        entity_id="e1",
        features={"amount": 1},
        as_of="2026-01-01T00:00:00Z",
    )
    upsert_feature(
        tenant_id="t1",
        entity_type="user",
        entity_id="e1",
        features={"amount": 9},
        as_of="2026-06-01T00:00:00Z",
    )
    early = get_features(
        tenant_id="t1", entity_type="user", entity_id="e1", as_of="2026-02-01T00:00:00Z"
    )
    assert early["amount"] == 1
    train, hold = holdout_split(
        [{"as_of": "2026-01-01T00:00:00Z"}, {"as_of": "2026-09-01T00:00:00Z"}],
        cutoff="2026-06-01T00:00:00Z",
    )
    assert len(train) == 1 and len(hold) == 1


def test_pit_as_of_iso_later_snapshot_does_not_leak() -> None:
    """Fractional ISO sorts before `Z`; later wall time must still be excluded."""
    upsert_feature(
        tenant_id="t-pit",
        entity_type="user",
        entity_id="e-pit",
        features={"amount": 1},
        as_of="2026-01-01T10:00:00Z",
    )
    upsert_feature(
        tenant_id="t-pit",
        entity_type="user",
        entity_id="e-pit",
        features={"amount": 9},
        as_of="2026-01-01T10:00:00.500Z",
    )
    early = get_features(
        tenant_id="t-pit",
        entity_type="user",
        entity_id="e-pit",
        as_of="2026-01-01T10:00:00Z",
    )
    assert early.get("amount") == 1


def test_tenant_isolation_no_cross_read() -> None:
    upsert_feature(
        tenant_id="tenant-a",
        entity_type="user",
        entity_id="shared-e",
        features={"amount": 1},
        as_of="2026-01-01T00:00:00Z",
    )
    upsert_feature(
        tenant_id="tenant-b",
        entity_type="user",
        entity_id="shared-e",
        features={"amount": 9},
        as_of="2026-01-01T00:00:00Z",
    )
    a = get_features(
        tenant_id="tenant-a",
        entity_type="user",
        entity_id="shared-e",
        as_of="2026-01-02T00:00:00Z",
    )
    b = get_features(
        tenant_id="tenant-b",
        entity_type="user",
        entity_id="shared-e",
        as_of="2026-01-02T00:00:00Z",
    )
    assert a.get("amount") == 1
    assert b.get("amount") == 9


def test_ring_job_offline() -> None:
    req = {
        "schema_id": JOB_REQUEST_SCHEMA,
        "tenant_id": "t1",
        "edges": [{"src": "a", "dst": "b"}, {"src": "a", "dst": "c"}],
    }
    validate_ring_request(req)
    out = run_ring_job(req)
    assert out["live"] is False
    assert out["tags"][0]["entity_id"] == "a"


@pytest.mark.asyncio
async def test_vendor_score_empty_and_timeout(monkeypatch) -> None:
    monkeypatch.delenv("VENDOR_SCORE_URL", raising=False)
    assert vendor_score_url() == ""
    assert await fetch_vendor_score(None, tenant_id="t", entity_id="e") is None
    monkeypatch.setenv("VENDOR_SCORE_URL", "http://score.test")

    class _Http:
        async def get(self, *_a, **_k):
            raise TimeoutError("slow")

    assert await fetch_vendor_score(_Http(), tenant_id="t", entity_id="e") is None
