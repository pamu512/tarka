"""G5.3: join_rate / labeled_receipt_rate on loop_metrics. null ≠ 0.0 theater."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from decision_api.label_horizon import horizon_days
from decision_api.loop_metrics import compute_loop_metrics


def _ts(day: int, hour: int = 0) -> str:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day, hours=hour)


def _iso(day: int, hour: int = 0) -> str:
    return _ts(day, hour).isoformat()


def _receipt(token: str, *, tenant_id: str, decided_day: int = 0) -> dict:
    return {
        "evaluation_token": token,
        "trace_id": token,
        "tenant_id": tenant_id,
        "entity_id": f"e-{token}",
        "created_at": _iso(decided_day),
        "decided_at": _iso(decided_day),
    }


def _labels(items: list[tuple[str, str, int, int]]) -> dict:
    """(token, kind, decided_day, labeled_day) → store maps."""
    kinds: dict[str, str] = {}
    decided: dict[str, str] = {}
    labeled: dict[str, str] = {}
    for token, kind, decided_day, labeled_day in items:
        kinds[token] = kind
        decided[token] = _iso(decided_day)
        labeled[token] = _iso(labeled_day)
    return {
        "label_kind_by_trace": kinds,
        "decided_at_by_trace": decided,
        "labeled_at_by_trace": labeled,
    }


def _reason(out: dict, field: str) -> str | None:
    unknown = out.get("unknown_reasons") or {}
    return unknown.get(field) or out.get("join_rate_reason")


def test_join_rate_labels_in_horizon_are_a_real_ratio():
    receipts = [
        _receipt("t1", tenant_id="acme"),
        _receipt("t2", tenant_id="acme"),
        _receipt("t3", tenant_id="acme"),
        _receipt("t4", tenant_id="acme"),
    ]
    # two of four labeled inside the tenant EXAMPLE fp window
    labels = _labels(
        [
            ("t1", "fp", 0, 1),
            ("t2", "fp", 0, 1),
        ]
    )
    out = compute_loop_metrics(
        [],
        labels,
        tenant_id="acme",
        receipts=receipts,
    )
    assert out["schema_id"] == "tarka.loop_metrics/v1"
    assert out["join_rate"] == 0.5
    assert out["labeled_receipt_rate"] == 0.5
    assert out["labeled_receipt_count"] == 2
    assert out["receipt_count"] == 4
    assert _reason(out, "join_rate") in (None, "")
    assert _reason(out, "labeled_receipt_rate") in (None, "")


def test_join_rate_empty_tenant_is_null_not_zero():
    out = compute_loop_metrics(
        [],
        _labels([("t1", "fp", 0, 1)]),
        tenant_id="",
        receipts=[_receipt("t1", tenant_id="acme")],
    )
    assert out["join_rate"] is None
    assert out["labeled_receipt_rate"] is None
    assert out["join_rate"] != 0.0
    assert _reason(out, "join_rate") == "empty_tenant"


def test_join_rate_no_receipts_is_null_not_zero():
    out = compute_loop_metrics(
        [],
        _labels([("t1", "fp", 0, 1)]),
        tenant_id="acme",
        receipts=[],
    )
    assert out["join_rate"] is None
    assert out["labeled_receipt_rate"] is None
    assert _reason(out, "join_rate") == "no_receipts"


def test_join_rate_missing_receipt_store_is_null_not_zero():
    out = compute_loop_metrics(
        [],
        _labels([("t1", "fp", 0, 1)]),
        tenant_id="acme",
    )
    assert out["join_rate"] is None
    assert out["labeled_receipt_rate"] is None
    assert _reason(out, "join_rate") == "receipt_store_absent"


def test_join_rate_no_labels_is_null_not_zero():
    out = compute_loop_metrics(
        [],
        {},
        tenant_id="acme",
        receipts=[_receipt("t1", tenant_id="acme")],
    )
    assert out["join_rate"] is None
    assert out["labeled_receipt_rate"] is None
    assert out["join_rate"] != 0.0
    assert _reason(out, "join_rate") == "no_labels"


def test_tenant_a_labels_never_count_toward_tenant_b():
    acme_receipts = [
        _receipt("a1", tenant_id="acme"),
        _receipt("a2", tenant_id="acme"),
    ]
    acme_labels = _labels([("a1", "fp", 0, 1), ("a2", "fp", 0, 1)])
    demo_receipts = [_receipt("b1", tenant_id="demo")]
    acme = compute_loop_metrics(
        [],
        acme_labels,
        tenant_id="acme",
        receipts=acme_receipts,
    )
    demo = compute_loop_metrics(
        [],
        acme_labels,
        tenant_id="demo",
        receipts=demo_receipts,
    )
    assert acme["join_rate"] == 1.0
    assert acme["labeled_receipt_rate"] == 1.0
    assert demo["join_rate"] != acme["join_rate"]
    assert demo["labeled_receipt_rate"] != acme["labeled_receipt_rate"]
    assert demo["join_rate"] == 0.0
    assert demo["labeled_receipt_count"] == 0
    assert demo["receipt_count"] == 1


def test_horizon_window_comes_from_tenant_example_policy(monkeypatch: pytest.MonkeyPatch):
    kind = "fp"
    window = horizon_days(kind)
    receipts = [_receipt("t1", tenant_id="acme")]
    outside = _labels([("t1", kind, 0, window + 1)])
    inside = _labels([("t1", kind, 0, max(0, window - 1))])

    missed = compute_loop_metrics(
        [],
        outside,
        tenant_id="acme",
        receipts=receipts,
    )
    assert missed["join_rate"] == 0.0
    assert missed["labeled_receipt_rate"] == 0.0
    assert missed["labeled_receipt_count"] == 0

    hit = compute_loop_metrics(
        [],
        inside,
        tenant_id="acme",
        receipts=receipts,
    )
    assert hit["join_rate"] == 1.0
    assert hit["labeled_receipt_rate"] == 1.0

    monkeypatch.setenv(
        "TARKA_LABEL_HORIZON_JSON",
        f'{{"{kind}": {{"window_days": {window + 10}}}}}',
    )
    from decision_api import label_horizon

    assert label_horizon.horizon_days(kind) == window + 10
    widened = compute_loop_metrics(
        [],
        outside,
        tenant_id="acme",
        receipts=receipts,
    )
    assert widened["join_rate"] == 1.0


@pytest.mark.asyncio
async def test_http_loop_metrics_exposes_join_rate_fields(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from decision_api.config import settings
    from decision_api.observe_drafts import router

    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/v1/observe/loop-metrics", params={"tenant_id": "acme"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "join_rate" in body
    assert "labeled_receipt_rate" in body
    assert body["join_rate"] is None
    assert body["labeled_receipt_rate"] is None
    unknown = body.get("unknown_reasons") or {}
    reason = unknown.get("join_rate") or body.get("join_rate_reason")
    assert reason in {"no_receipts", "receipt_store_absent", "no_labels"}
