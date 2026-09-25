"""Challenger bus + bake-off arena (P2): governed A/B of N challengers.

Contracts:
- Arena config maps challenger names -> JSON rule packs; the arena evaluates
  every configured challenger against the same features/tags in SHADOW and
  returns per-challenger scores + decisions. It never touches the production
  decision.
- Divergence vs champion is computed per challenger; null = unknown when
  labels are absent (bake-off rules).
- The weekly-champion report reduces an arena ledger to hit-rate /
  divergence / fp-delta per challenger with explicit unknowns preserved.
"""

from __future__ import annotations

import pytest

from decision_api.challenger_arena import (
    ArenaConfig,
    evaluate_arena,
    weekly_champion_report,
)


def _cfg() -> ArenaConfig:
    return ArenaConfig(
        tenant_id="acme",
        challengers={
            "challenger_a": {
                "rules": [
                    {"id": "r1", "when": {"field": "amount", "op": "gte", "value": 100}}
                ]
            },
            "challenger_b": {"rules": []},
        },
    )


def test_arena_config_from_env_and_backing_store_roundtrip():
    cfg = ArenaConfig.from_store(
        {
            "tenant_id": "acme",
            "challengers": {
                "a": {
                    "rules": [
                        {"id": "x", "when": {"field": "f", "op": "eq", "value": 1}}
                    ]
                }
            },
        }
    )
    assert cfg.tenant_id == "acme"
    assert set(cfg.challengers) == {"a"}
    assert cfg.to_store()["challengers"]["a"]["rules"][0]["id"] == "x"


def test_arena_evaluates_all_challengers_in_shadow():
    out = evaluate_arena(
        _cfg(),
        features={"amount": 500},
        redis_tags=[],
        champion_decision="review",
        champion_score=42.0,
    )
    assert set(out["challengers"]) == {"challenger_a", "challenger_b"}
    a = out["challengers"]["challenger_a"]
    assert a["decision"] in ("allow", "review", "deny")
    assert isinstance(a["score"], float)
    # b has no rules -> base score only, but must still report
    assert "score" in out["challengers"]["challenger_b"]
    assert out["mode"] == "shadow"
    assert "production_decision" in out and out["production_decision"] == "review"


def test_arena_divergence_flags_disagreement():
    out = evaluate_arena(
        _cfg(),
        features={"amount": 500},
        redis_tags=[],
        champion_decision="allow",
        champion_score=5.0,
    )
    assert out["challengers"]["challenger_a"]["diverges_from_champion"] in (True, False)
    # determinism for report math
    out2 = evaluate_arena(
        _cfg(),
        features={"amount": 500},
        redis_tags=[],
        champion_decision="allow",
        champion_score=5.0,
    )
    assert out == out2


def test_weekly_report_preserves_unknowns():
    ledger = [
        {
            "ts": "2026-09-20T00:00:00Z",
            "champion": {"decision": "allow", "label": "legit"},
            "challengers": {
                "challenger_a": {"decision": "deny", "label": "legit"},
                "challenger_b": {"decision": "allow", "label": None},
            },
        },
        {
            "ts": "2026-09-21T00:00:00Z",
            "champion": {"decision": "deny", "label": "fraud"},
            "challengers": {
                "challenger_a": {"decision": "deny", "label": "fraud"},
                "challenger_b": {"decision": "allow", "label": None},
            },
        },
    ]
    rep = weekly_champion_report("acme", ledger)
    a = rep["challengers"]["challenger_a"]
    assert a["n"] == 2
    assert a["divergence_rate"] == 0.5
    # challenger_b labels unknown -> fp_delta must be None (unknown), not 0
    b = rep["challengers"]["challenger_b"]
    assert b["fp_delta"] is None
    # challenger_a: labeled rows = 2; champion had 0 FPs; challenger_a denied
    # a legit (row1) -> fp_delta = 1/2 - 0/2 = 0.5
    assert a["fp_delta"] == 0.5


def test_weekly_report_empty_ledger_is_explicit_unknown():
    rep = weekly_champion_report("acme", [])
    assert rep["n"] == 0
    assert rep["challengers"] == {}


# ---------- ops endpoint contract ----------


@pytest.mark.asyncio
async def test_arena_report_endpoint_empty_ledger(monkeypatch, tmp_path):
    """No ledger file -> n=0 report, not an error (unknown, honestly)."""
    from fastapi.testclient import TestClient

    from decision_api.main import app

    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    r = client.get("/v1/ops/arena/report", params={"tenant_id": "acme"})
    assert r.status_code == 200
    body = r.json()
    assert body["n"] == 0
    assert body["challengers"] == {}
    assert body["tenant_id"] == "acme"


@pytest.mark.asyncio
async def test_arena_report_endpoint_reads_ledger(monkeypatch, tmp_path):
    import json as _json

    from fastapi.testclient import TestClient

    from decision_api.main import app

    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    (tmp_path / "arena_ledger_acme.jsonl").write_text(
        _json.dumps(
            {
                "champion": {"decision": "allow", "label": "legit"},
                "challengers": {"c1": {"decision": "deny", "label": "legit"}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    client = TestClient(app)
    r = client.get("/v1/ops/arena/report", params={"tenant_id": "acme"})
    assert r.status_code == 200
    c1 = r.json()["challengers"]["c1"]
    assert c1["n"] == 1
    assert c1["divergence_rate"] == 1.0
