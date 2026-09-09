"""Effectiveness tick: numbered Suggest Propose Demote only. Never demotes."""

from __future__ import annotations

from pathlib import Path

import pytest

from decision_api.effectiveness_tick import (
    load_suggestions,
    run_effectiveness_tick,
)

_TICK_SRC = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "decision_api"
    / "effectiveness_tick.py"
)


def _active(name: str, tenant_id: str = "acme") -> dict:
    return {"name": name, "mode": "active", "tenant_id": tenant_id}


def _obs(
    pack_id: str, tenant_id: str, *, diverged: bool, hits: list, trace_id: str = ""
) -> dict:
    return {
        "pack_id": pack_id,
        "tenant_id": tenant_id,
        "diverged": diverged,
        "shadow_rule_hits": hits,
        "trace_id": trace_id,
    }


def test_rotting_pack_emits_numbered_suggestion():
    packs = [_active("rot_pack")]
    observations = [
        _obs("rot_pack", "acme", diverged=True, hits=["r1"], trace_id="t-fp"),
        _obs("rot_pack", "acme", diverged=True, hits=["r1"], trace_id="t2"),
        _obs("rot_pack", "acme", diverged=False, hits=[], trace_id="t3"),
        _obs("rot_pack", "acme", diverged=True, hits=["r2"], trace_id="t4"),
    ]
    labels = {"label_kind_by_trace": {"t-fp": "fp"}}
    out = run_effectiveness_tick(
        packs,
        observations,
        labels,
        tenant_id="acme",
    )
    assert len(out["suggestions"]) == 1
    row = out["suggestions"][0]
    assert row["pack_id"] == "rot_pack"
    assert row["rule_hit_rate"] == 0.75
    assert row["shadow_divergence"] == 0.75
    assert row["fp_count"] == 1
    assert row["reason_code"]
    assert row["action"] == "suggest_propose_demote"


def test_tick_never_calls_demote_or_promote(monkeypatch):
    called: list[str] = []

    def _boom(name: str):
        def _inner(*_a, **_k):
            called.append(name)
            raise AssertionError(f"tick must not call {name}")

        return _inner

    monkeypatch.setattr("decision_api.l2_draft.propose_demote", _boom("propose_demote"))
    monkeypatch.setattr("decision_api.l2_draft.confirm_demote", _boom("confirm_demote"))
    monkeypatch.setattr(
        "decision_api.shadow_auto_promote.maybe_auto_promote_shadow",
        _boom("maybe_auto_promote_shadow"),
    )
    src = _TICK_SRC.read_text(encoding="utf-8")
    for banned in (
        "propose_demote(",
        "confirm_demote(",
        "maybe_auto_promote",
        "force_live",
        "auto_demote",
    ):
        assert banned not in src, banned

    packs = [_active("rot_pack")]
    observations = [
        _obs("rot_pack", "acme", diverged=True, hits=["r1"]),
        _obs("rot_pack", "acme", diverged=True, hits=["r1"]),
    ]
    out = run_effectiveness_tick(packs, observations, {}, tenant_id="acme")
    assert called == []
    assert packs[0]["mode"] == "active"
    assert "demote" not in (packs[0].get("lifecycle") or {})
    assert out["suggestions"][0]["pack_id"] == "rot_pack"


def test_empty_tenant_is_empty_list():
    out = run_effectiveness_tick(
        [_active("rot_pack")],
        [_obs("rot_pack", "acme", diverged=True, hits=["r1"])],
        {},
        tenant_id="",
    )
    assert out["suggestions"] == []


def test_unknown_metrics_are_not_suggestions():
    out = run_effectiveness_tick([_active("quiet")], [], {}, tenant_id="acme")
    assert out["suggestions"] == []


def test_tenant_isolation():
    packs = [_active("acme_rot", "acme"), _active("demo_rot", "demo")]
    observations = [
        _obs("acme_rot", "acme", diverged=True, hits=["r1"]),
        _obs("acme_rot", "acme", diverged=True, hits=["r1"]),
        _obs("demo_rot", "demo", diverged=True, hits=["r1"]),
        _obs("demo_rot", "demo", diverged=True, hits=["r1"]),
    ]
    acme = run_effectiveness_tick(packs, observations, {}, tenant_id="acme")
    demo = run_effectiveness_tick(packs, observations, {}, tenant_id="demo")
    assert [r["pack_id"] for r in acme["suggestions"]] == ["acme_rot"]
    assert [r["pack_id"] for r in demo["suggestions"]] == ["demo_rot"]


def test_persist_then_load_is_tenant_scoped(tmp_path, monkeypatch):
    from decision_api.config import settings

    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    packs = [_active("rot_pack")]
    observations = [
        _obs("rot_pack", "acme", diverged=True, hits=["r1"]),
        _obs("rot_pack", "acme", diverged=True, hits=["r1"]),
    ]
    written = run_effectiveness_tick(
        packs, observations, {}, tenant_id="acme", persist=True
    )
    assert written["persisted"] is True
    loaded = load_suggestions("acme")
    assert [r["pack_id"] for r in loaded] == ["rot_pack"]
    assert load_suggestions("demo") == []
    dry = run_effectiveness_tick(
        packs, observations, {}, tenant_id="acme", persist=False
    )
    assert dry["persisted"] is False


@pytest.mark.asyncio
async def test_http_tick_and_read_path(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from decision_api.config import settings
    from decision_api.observe_drafts import ops_router, router

    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    (tmp_path / "rot.json").write_text(
        '{"name":"rot_pack","mode":"active","tenant_id":"acme"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "decision_api.observe_drafts.get_observations",
        lambda _n=10000: [
            _obs("rot_pack", "acme", diverged=True, hits=["r1"]),
            _obs("rot_pack", "acme", diverged=True, hits=["r1"]),
        ],
    )
    app = FastAPI()
    app.include_router(router)
    app.include_router(ops_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        empty = await c.get(
            "/v1/observe/demote-suggestions", params={"tenant_id": "acme"}
        )
        assert empty.status_code == 200
        assert empty.json()["suggestions"] == []
        tick = await c.post(
            "/v1/ops/effectiveness-tick",
            params={"tenant_id": "acme"},
        )
        assert tick.status_code == 200, tick.text
        body = tick.json()
        assert body["suggestions"][0]["pack_id"] == "rot_pack"
        assert body["suggestions"][0]["action"] == "suggest_propose_demote"
        listed = await c.get(
            "/v1/observe/demote-suggestions", params={"tenant_id": "acme"}
        )
    assert listed.status_code == 200
    assert listed.json()["suggestions"][0]["pack_id"] == "rot_pack"
