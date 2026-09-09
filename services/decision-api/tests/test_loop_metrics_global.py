"""D8.2 — tenant-level evaluate_count / action_mix / shadow_divergence.

null = unknown. Do not bind LoopScoreboard. Do not rebuild pack_metrics[].
"""

from __future__ import annotations

import pytest

from decision_api.loop_metrics import compute_loop_metrics


def _eval(tenant: str, action: str, *, trace_id: str = "") -> dict:
    return {
        "tenant_id": tenant,
        "action": action,
        "trace_id": trace_id or f"{tenant}-{action}",
    }


def test_evaluate_count_matches_synthetic_n():
    evaluations = [_eval("acme", "allow", trace_id=f"t{i}") for i in range(7)]
    out = compute_loop_metrics([], {}, tenant_id="acme", evaluations=evaluations)
    assert out["evaluate_count"] == 7
    assert out["schema_id"] == "tarka.loop_metrics/v1"


def test_action_mix_matches_allow_deny_flag():
    evaluations = [
        _eval("acme", "ALLOW", trace_id="a1"),
        _eval("acme", "DENY", trace_id="d1"),
        _eval("acme", "FLAG", trace_id="f1"),
        _eval("acme", "allow", trace_id="a2"),
    ]
    out = compute_loop_metrics([], {}, tenant_id="acme", evaluations=evaluations)
    assert out["action_mix"] == {"allow": 2, "deny": 1, "flag": 1}
    assert "review" not in out["action_mix"]


def test_shadow_divergence_from_paired_live_shadow():
    observations = [
        {
            "tenant_id": "acme",
            "production_decision": "allow",
            "shadow_decision": "deny",
            "diverged": True,
        },
        {
            "tenant_id": "acme",
            "production_decision": "allow",
            "shadow_decision": "allow",
            "diverged": False,
        },
    ]
    out = compute_loop_metrics(
        [],
        {},
        tenant_id="acme",
        evaluations=[_eval("acme", "allow")],
        observations=observations,
    )
    assert out["shadow_divergence"] == 0.5
    assert out["rule_hit_rate"] is None
    assert out["pack_metrics"] == []


def test_empty_tenant_and_missing_store_are_null_not_fake_zero():
    empty = compute_loop_metrics([], {}, tenant_id="")
    assert empty["evaluate_count"] is None
    assert empty["action_mix"] is None
    assert empty["shadow_divergence"] is None
    assert empty["reason_code"] == "empty_tenant"

    missing = compute_loop_metrics([], {}, tenant_id="acme")
    assert missing["evaluate_count"] is None
    assert missing["action_mix"] is None
    assert missing["shadow_divergence"] is None
    assert missing["evaluate_count"] != 0
    assert missing["shadow_divergence"] != 0.0
    reasons = missing.get("unknown_reasons") or {}
    assert missing["reason_code"] in {
        "evaluate_store_absent",
        "no_shadow_live_pairs",
    }
    assert reasons.get("evaluate_count") == "evaluate_store_absent"
    assert reasons.get("shadow_divergence") == "no_shadow_live_pairs"


def test_global_metrics_tenant_isolation():
    evaluations = [
        _eval("acme", "allow", trace_id="a1"),
        _eval("demo", "deny", trace_id="d1"),
    ]
    observations = [
        {
            "tenant_id": "acme",
            "production_decision": "allow",
            "shadow_decision": "deny",
            "diverged": True,
        },
        {
            "tenant_id": "demo",
            "production_decision": "deny",
            "shadow_decision": "deny",
            "diverged": False,
        },
    ]
    acme = compute_loop_metrics(
        [],
        {},
        tenant_id="acme",
        evaluations=evaluations,
        observations=observations,
    )
    demo = compute_loop_metrics(
        [],
        {},
        tenant_id="demo",
        evaluations=evaluations,
        observations=observations,
    )
    assert acme["evaluate_count"] == 1
    assert acme["action_mix"] == {"allow": 1}
    assert acme["shadow_divergence"] == 1.0
    assert demo["evaluate_count"] == 1
    assert demo["action_mix"] == {"deny": 1}
    assert demo["shadow_divergence"] == 0.0


def test_pack_metrics_unchanged_when_globals_fill():
    packs = [{"name": "pack_a", "tenant_id": "acme"}]
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
    ]
    out = compute_loop_metrics(
        packs,
        {},
        tenant_id="acme",
        evaluations=[_eval("acme", "flag")],
        observations=observations,
    )
    rows = out["pack_metrics"]
    assert len(rows) == 1
    assert rows[0]["pack_id"] == "pack_a"
    assert rows[0]["rule_hit_rate"] == 0.5
    assert rows[0]["shadow_divergence"] == 0.5
    assert out["evaluate_count"] == 1
    assert out["action_mix"] == {"flag": 1}
    assert out["shadow_divergence"] == 0.5


@pytest.mark.asyncio
async def test_http_loop_metrics_and_bakeoff_expose_globals(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from decision_api.config import settings
    from decision_api.gnn_loop.receipts import append_receipt
    from decision_api.observe_drafts import ops_router, router
    from decision_api.shadow import record_observation

    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    append_receipt(
        "acme",
        {"tenant_id": "acme", "action": "allow", "trace_id": "http-1"},
    )
    append_receipt(
        "acme",
        {"tenant_id": "acme", "action": "deny", "trace_id": "http-2"},
    )
    record_observation(
        "http-1",
        {"decision": "allow"},
        {"shadow_decision": "deny"},
    )
    app = FastAPI()
    app.include_router(router)
    app.include_router(ops_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        loop = await c.get("/v1/observe/loop-metrics", params={"tenant_id": "acme"})
        bake = await c.get("/v1/ops/bakeoff", params={"tenant_id": "acme"})
        ghost = await c.get("/v1/observe/loop-metrics", params={"tenant_id": "ghost"})
    assert loop.status_code == 200, loop.text
    body = loop.json()
    assert body["schema_id"] == "tarka.loop_metrics/v1"
    assert body["evaluate_count"] == 2
    assert body["action_mix"] == {"allow": 1, "deny": 1}
    assert body["shadow_divergence"] == 1.0
    assert bake.status_code == 200
    assert bake.json()["evaluate_count"] == 2
    assert ghost.status_code == 200
    missing = ghost.json()
    assert missing["evaluate_count"] is None
    assert missing["action_mix"] is None
    assert missing["shadow_divergence"] is None
    assert missing["reason_code"]
