"""Loop scoreboard v1 — numbers only, no CRM."""

from __future__ import annotations

import pytest

from decision_api.loop_metrics import compute_loop_metrics, compute_pack_metrics


def test_loop_metrics_from_drafts_and_fp_labels():
    packs = [
        {
            "authored_by": "human",
            "is_ai_authored": False,
            "source_key": "leftover:lo-1",
            "lifecycle": {
                "state": "observe",
                "created_at": "2026-09-07T00:00:00+00:00",
                "observe_entered_at": "2026-09-07T00:00:00.200000+00:00",
            },
        },
        {
            "authored_by": "scout",
            "is_ai_authored": True,
            "source_key": "hil:ovr-2",
            "lifecycle": {
                "state": "promoted",
                "created_at": "2026-09-07T00:00:00+00:00",
                "observe_entered_at": "2026-09-07T00:00:01+00:00",
                "promoted_at": "2026-09-07T00:00:11+00:00",
            },
        },
    ]
    labels = {
        "label_kind_by_trace": {"t1": "fp", "t2": "fraud"},
        "fp_cost_by_trace": {"t1": '{"amount": 12.5}'},
        "labeled_at_by_trace": {"t1": "2026-09-07T00:00:05+00:00"},
        "decided_at_by_trace": {"t1": "2026-09-07T00:00:00+00:00"},
    }
    out = compute_loop_metrics(
        packs,
        labels,
        ai_blocked=1,
        ai_passed=1,
    )
    assert out["schema_id"] == "tarka.loop_metrics/v1"
    assert out["drafts_to_observe"]["human"] == 1
    assert out["drafts_to_observe"]["ai"] == 1
    assert out["ai_backtest_block_rate"] == 0.5
    assert out["fp_count"] == 1
    assert out["fp_cost_sum"] == 12.5
    assert out["leftover_to_draft_ms"]["p50"] == 200
    assert out["promote_ttl_ms"]["p50"] == 10000
    assert out["label_latency_ms"]["p50"] == 5000
    assert out["leftover_mint_rate"] == 0.5
    assert out["demote_propose_count"] == 0
    assert out["evaluate_count"] is None
    assert out["action_mix"] is None
    assert out["shadow_divergence"] is None
    assert "label_latency_hours" in out
    assert "promote_ttl_hours" in out


def test_loop_metrics_empty():
    out = compute_loop_metrics([], {}, ai_blocked=0, ai_passed=0)
    assert out["fp_count"] == 0
    assert out["ai_backtest_block_rate"] is None
    assert out["leftover_to_draft_ms"]["p50"] is None
    assert out["pack_metrics"] == []


def test_pack_metrics_from_shadow_observations():
    packs = [{"name": "pack_a", "tenant_id": "acme", "lifecycle": {"state": "observe"}}]
    observations = [
        {
            "pack_id": "pack_a",
            "tenant_id": "acme",
            "diverged": True,
            "shadow_rule_hits": ["r1"],
        },
        {
            "pack_id": "pack_a",
            "tenant_id": "acme",
            "diverged": False,
            "shadow_rule_hits": [],
        },
        {
            "pack_id": "pack_a",
            "tenant_id": "demo",
            "diverged": True,
            "shadow_rule_hits": ["leak"],
        },
    ]
    out = compute_loop_metrics(
        packs,
        {},
        tenant_id="acme",
        observations=observations,
    )
    assert out["rule_hit_rate"] is None
    assert out["shadow_divergence"] == 0.5
    rows = out["pack_metrics"]
    assert len(rows) == 1
    row = rows[0]
    assert row["pack_id"] == "pack_a"
    assert row["rule_hit_rate"] == 0.5
    assert row["shadow_divergence"] == 0.5
    assert row["window"] == "7d"
    assert row["as_of"]


def test_pack_metrics_empty_tenant_is_empty_list():
    packs = [{"name": "pack_a", "tenant_id": "acme"}]
    assert (
        compute_pack_metrics(
            packs, [{"pack_id": "pack_a", "diverged": True}], tenant_id=""
        )
        == []
    )


def test_pack_metrics_unknown_when_no_observations():
    rows = compute_pack_metrics(
        [{"name": "pack_a", "tenant_id": "acme"}],
        [],
        tenant_id="acme",
    )
    assert rows[0]["rule_hit_rate"] is None
    assert rows[0]["shadow_divergence"] is None
    assert rows[0]["as_of"] is None


def test_pack_metrics_tenant_isolation():
    packs = [
        {"name": "acme_pack", "tenant_id": "acme"},
        {"name": "demo_pack", "tenant_id": "demo"},
    ]
    observations = [
        {
            "pack_id": "acme_pack",
            "tenant_id": "acme",
            "diverged": True,
            "shadow_rule_hits": ["r1"],
        },
        {
            "pack_id": "demo_pack",
            "tenant_id": "demo",
            "diverged": True,
            "shadow_rule_hits": ["r1"],
        },
    ]
    acme = compute_pack_metrics(packs, observations, tenant_id="acme")
    assert [r["pack_id"] for r in acme] == ["acme_pack"]
    demo = compute_pack_metrics(packs, observations, tenant_id="demo")
    assert [r["pack_id"] for r in demo] == ["demo_pack"]


@pytest.mark.asyncio
async def test_http_loop_metrics(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from decision_api.config import settings
    from decision_api.observe_drafts import router

    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    (tmp_path / "l2_x.json").write_text(
        '{"name":"l2_x","source_key":"leftover:lo-1","authored_by":"human",'
        '"lifecycle":{"state":"observe","created_at":"2026-09-07T00:00:00+00:00",'
        '"observe_entered_at":"2026-09-07T00:00:00.200000+00:00"}}',
        encoding="utf-8",
    )
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/v1/observe/loop-metrics", params={"tenant_id": "acme"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_id"] == "tarka.loop_metrics/v1"
    assert body["drafts_to_observe"]["human"] == 1
    assert "leftover_mint_rate" in body
    assert "demote_propose_count" in body
    assert "pack_metrics" in body
    assert isinstance(body["pack_metrics"], list)


@pytest.mark.asyncio
async def test_http_bakeoff_alias(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from decision_api.config import settings
    from decision_api.observe_drafts import ops_router

    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    app = FastAPI()
    app.include_router(ops_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/v1/ops/bakeoff", params={"tenant_id": "acme"})
        q = await c.get("/v1/ops/queue-seam")
        e = await c.get("/v1/ops/enforcement-mode")
    assert r.status_code == 200
    assert r.json()["schema_id"] == "tarka.loop_metrics/v1"
    assert q.status_code == 200
    assert q.json()["connected"] is False
    assert e.json()["enforcement_mode"] == "emit_only"
