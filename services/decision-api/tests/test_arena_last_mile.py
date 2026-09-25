"""Arena last mile: config + ledger writes (doc 13 step 1).

Contracts:
- load_arena_config reads rules/arena/<tenant>.json; missing file = no arena
  (zero overhead, no error).
- record_arena_row appends one jsonl row per evaluate when challengers are
  configured; fail-soft (never breaks evaluate); ring-bounded.
- The evaluate pipeline calls both when a config exists (integration seam
  tested via _maybe_arena_snapshot).
"""

from __future__ import annotations

import json
from pathlib import Path


from decision_api.challenger_arena import (
    evaluate_arena,
    load_arena_config,
    record_arena_row,
    _maybe_arena_snapshot,
)


def _write_cfg(tmp_path: Path, tenant: str = "acme") -> None:
    d = tmp_path / "arena"
    d.mkdir(exist_ok=True)
    (d / f"{tenant}.json").write_text(
        json.dumps(
            {
                "tenant_id": tenant,
                "challengers": {
                    "c1": {
                        "rules": [
                            {
                                "id": "r1",
                                "when": {"field": "amount", "op": "gte", "value": 100},
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_load_arena_config_missing_file_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "decision_api.challenger_arena._arena_rules_dir", lambda: tmp_path / "arena"
    )
    assert load_arena_config("ghost") is None


def test_record_arena_row_appends_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "decision_api.challenger_arena._arena_rules_dir", lambda: tmp_path / "arena"
    )
    _write_cfg(tmp_path)
    cfg = load_arena_config("acme")
    assert cfg is not None and set(cfg.challengers) == {"c1"}

    arena_out = evaluate_arena(
        cfg,
        features={"amount": 500},
        redis_tags=[],
        champion_decision="allow",
        champion_score=5.0,
    )
    assert record_arena_row("acme", arena_out) is True
    ledger = tmp_path / "arena_ledger_acme.jsonl"
    assert ledger.is_file()
    rows = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
    assert len(rows) == 1
    assert rows[0]["challengers"]["c1"]["decision"] in ("allow", "review", "deny")


def test_record_arena_row_ring_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "decision_api.challenger_arena._arena_rules_dir", lambda: tmp_path / "arena"
    )
    _write_cfg(tmp_path)
    cfg = load_arena_config("acme")
    out = evaluate_arena(
        cfg, features={}, redis_tags=[], champion_decision="allow", champion_score=5.0
    )
    for _ in range(3_050):
        assert record_arena_row("acme", out)
    rows = [
        json.loads(x)
        for x in (tmp_path / "arena_ledger_acme.jsonl").read_text().splitlines()
        if x.strip()
    ]
    assert len(rows) <= 3_000


def test_record_arena_row_fail_soft_on_bad_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    # dir becomes a file -> write must fail soft (False), never raise
    bad = tmp_path / "arena_ledger_acme.jsonl"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("x")
    monkeypatch.setattr(
        "decision_api.challenger_arena._arena_ledger_path",
        lambda tenant: bad / "sub" / "x.jsonl",
    )
    assert record_arena_row("acme", {"anything": True}) is False


def test_maybe_arena_snapshot_noop_without_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "decision_api.challenger_arena._arena_rules_dir", lambda: tmp_path / "arena"
    )
    # no config file -> returns None quickly, writes nothing
    out = _maybe_arena_snapshot(
        tenant_id="ghost",
        features={"amount": 1},
        redis_tags=[],
        champion_decision="allow",
        champion_score=1.0,
    )
    assert out is None


# ---------- config API routes ----------


def _client(monkeypatch, tmp_path, roles=("analyst", "admin")):
    """TestClient with a synthetic auth_user injected (roles configurable)."""
    from fastapi.testclient import TestClient

    from decision_api.main import app

    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "decision_api.challenger_arena._arena_rules_dir", lambda: tmp_path / "arena"
    )

    import auth_rbac
    from auth_rbac import AuthUser

    user = AuthUser(user_id="test-user", roles=list(roles), auth_type="test")

    async def _fake_auth(request):
        return user

    monkeypatch.setattr(auth_rbac, "_authenticate", _fake_auth)
    return TestClient(app)


def test_arena_config_get_unconfigured(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.get("/v1/ops/arena/config", params={"tenant_id": "acme"})
    # allow-insecure-desk test env: require_role permits when no API_KEYS set
    assert r.status_code == 200
    assert r.json() == {"configured": False, "challengers": {}}


def test_arena_config_put_then_get_roundtrip(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    pack = {
        "rules": [{"id": "r1", "when": {"field": "amount", "op": "gte", "value": 100}}]
    }
    r = client.put(
        "/v1/ops/arena/config",
        params={"tenant_id": "acme"},
        json={"challengers": {"c1": pack}},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"configured": True, "challengers": ["c1"]}
    r2 = client.get("/v1/ops/arena/config", params={"tenant_id": "acme"})
    assert r2.status_code == 200
    body = r2.json()
    assert body["configured"] is True
    assert body["challengers"]["c1"]["rules"][0]["id"] == "r1"


def test_arena_config_put_rejects_bad_body(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put(
        "/v1/ops/arena/config",
        params={"tenant_id": "acme"},
        json={"challengers": {"c1": "not-a-pack"}},
    )
    assert r.status_code == 422


def test_arena_config_put_requires_admin_role(monkeypatch, tmp_path):
    """Analyst can read config but must NOT write it (governance write path)."""
    client = _client(monkeypatch, tmp_path, roles=("analyst",))
    r = client.put(
        "/v1/ops/arena/config",
        params={"tenant_id": "acme"},
        json={"challengers": {"c1": {"rules": []}}},
    )
    assert r.status_code == 403
