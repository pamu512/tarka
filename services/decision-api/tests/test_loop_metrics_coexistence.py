"""D8.4 — M3 pack_metrics[] and D8 GLOBAL keys coexist without clobber.

Filling one side must not drop or fake-zero the other. null = unknown, never 0%.
schema_id stays tarka.loop_metrics/v1. Do not fork tarka.pack_metrics/v1.
"""

from __future__ import annotations

import pytest

from decision_api.loop_metrics import (
    PACK_METRICS_SCHEMA_ID,
    SCHEMA_ID,
    compute_loop_metrics,
)


def _eval(tenant: str, action: str, *, trace_id: str = "") -> dict:
    return {
        "tenant_id": tenant,
        "action": action,
        "trace_id": trace_id or f"{tenant}-{action}",
    }


def _pack_obs(
    pack_id: str, *, tenant: str = "acme", diverged: bool, hits: list[str]
) -> dict:
    return {
        "pack_id": pack_id,
        "tenant_id": tenant,
        "diverged": diverged,
        "shadow_rule_hits": hits,
    }


def test_both_sides_present_when_globals_and_pack_metrics_fill():
    packs = [{"name": "pack_a", "tenant_id": "acme"}]
    observations = [
        _pack_obs("pack_a", diverged=True, hits=["r1"]),
        _pack_obs("pack_a", diverged=False, hits=[]),
    ]
    out = compute_loop_metrics(
        packs,
        {},
        tenant_id="acme",
        evaluations=[_eval("acme", "allow"), _eval("acme", "deny")],
        observations=observations,
    )
    assert out["schema_id"] == SCHEMA_ID == "tarka.loop_metrics/v1"
    assert out["evaluate_count"] == 2
    assert out["action_mix"] == {"allow": 1, "deny": 1}
    assert out["shadow_divergence"] == 0.5
    assert out["rule_hit_rate"] is None
    rows = out["pack_metrics"]
    assert len(rows) == 1
    assert rows[0]["schema_id"] == PACK_METRICS_SCHEMA_ID
    assert rows[0]["pack_id"] == "pack_a"
    assert rows[0]["rule_hit_rate"] == 0.5
    assert rows[0]["shadow_divergence"] == 0.5


def test_filling_globals_does_not_drop_or_zero_unknown_pack_row():
    packs = [{"name": "pack_a", "tenant_id": "acme"}]
    out = compute_loop_metrics(
        packs,
        {},
        tenant_id="acme",
        evaluations=[_eval("acme", "flag")],
        observations=[],
    )
    assert out["evaluate_count"] == 1
    assert out["action_mix"] == {"flag": 1}
    rows = out["pack_metrics"]
    assert len(rows) == 1
    assert rows[0]["pack_id"] == "pack_a"
    assert rows[0]["rule_hit_rate"] is None
    assert rows[0]["shadow_divergence"] is None
    assert rows[0]["as_of"] is None


def test_filling_pack_metrics_does_not_zero_unknown_evaluate_globals():
    packs = [{"name": "pack_a", "tenant_id": "acme"}]
    observations = [
        _pack_obs("pack_a", diverged=True, hits=["r1"]),
        _pack_obs("pack_a", diverged=False, hits=[]),
    ]
    out = compute_loop_metrics(
        packs,
        {},
        tenant_id="acme",
        observations=observations,
    )
    rows = out["pack_metrics"]
    assert len(rows) == 1
    assert rows[0]["rule_hit_rate"] == 0.5
    assert rows[0]["shadow_divergence"] == 0.5
    assert out["evaluate_count"] is None
    assert out["action_mix"] is None
    assert "evaluate_count" in (out.get("unknown_reasons") or {})


def test_empty_tenant_keeps_both_sides_unknown():
    out = compute_loop_metrics([], {}, tenant_id="")
    assert out["evaluate_count"] is None
    assert out["action_mix"] is None
    assert out["shadow_divergence"] is None
    assert out["pack_metrics"] == []
    assert out["evaluate_count"] != 0
    assert out["shadow_divergence"] != 0.0


@pytest.mark.asyncio
async def test_http_payload_keeps_globals_and_pack_row(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from decision_api.config import settings
    from decision_api.gnn_loop.receipts import append_receipt
    from decision_api.observe_drafts import ops_router, router

    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    (tmp_path / "l2_pack_a.json").write_text(
        '{"name":"pack_a","tenant_id":"acme","source_key":"leftover:lo-1",'
        '"authored_by":"human","lifecycle":{"state":"observe",'
        '"created_at":"2026-09-07T00:00:00+00:00",'
        '"observe_entered_at":"2026-09-07T00:00:00.200000+00:00"}}',
        encoding="utf-8",
    )
    append_receipt(
        "acme",
        {"tenant_id": "acme", "action": "allow", "trace_id": "coexist-1"},
    )
    append_receipt(
        "acme",
        {"tenant_id": "acme", "action": "deny", "trace_id": "coexist-2"},
    )
    app = FastAPI()
    app.include_router(router)
    app.include_router(ops_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        loop = await c.get("/v1/observe/loop-metrics", params={"tenant_id": "acme"})
        bake = await c.get("/v1/ops/bakeoff", params={"tenant_id": "acme"})
    assert loop.status_code == 200, loop.text
    body = loop.json()
    assert body["schema_id"] == "tarka.loop_metrics/v1"
    assert body["evaluate_count"] == 2
    assert body["action_mix"] == {"allow": 1, "deny": 1}
    rows = body["pack_metrics"]
    assert len(rows) == 1
    assert rows[0]["pack_id"] == "pack_a"
    assert rows[0]["rule_hit_rate"] is None
    assert rows[0]["shadow_divergence"] is None
    assert bake.status_code == 200
    assert bake.json()["evaluate_count"] == 2
    assert bake.json()["pack_metrics"][0]["rule_hit_rate"] is None
