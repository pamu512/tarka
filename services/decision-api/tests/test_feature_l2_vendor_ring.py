"""W5 L2 empty URL, W6 ring job, OPT vendor_score."""

from __future__ import annotations

import pytest

from decision_api.feature_l2 import (
    get_features,
    holdout_split,
    resolve_feature_source,
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
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs")
    assert resolve_feature_source() == "l2"


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
