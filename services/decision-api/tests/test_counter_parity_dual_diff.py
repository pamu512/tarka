"""Counter dual-diff parity artifact — critical L1 gate (not dry-run vanity)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "oss" / "counter_parity_dual_diff.py"
_FIXTURE = _REPO / "scripts" / "replay" / "fixtures" / "parity_smoke.jsonl"
_GOLDEN = _REPO / "scripts" / "replay" / "fixtures" / "parity_smoke_counters.json"


def _load_mod():
    spec = importlib.util.spec_from_file_location("counter_parity_dual_diff", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load_mod()


def test_parity_artifact_dual_diff_shape(tmp_path, mod, monkeypatch):
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    process = {
        entity_id: dict(spec["counters"])
        for entity_id, spec in golden["entities"].items()
    }

    async def _fake_compute(*_a, **_k):
        return process

    monkeypatch.setattr(mod, "_flush_redis_dbs", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_redis_zset_diffs", lambda *a, **k: [])
    monkeypatch.setattr(mod, "_run_redis_replay", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_compute_process_counters", _fake_compute)

    out = tmp_path / "counter_parity_last.json"
    artifact = mod.run(
        mode="dual_diff",
        out=out,
        fixture=_FIXTURE,
        golden=_GOLDEN,
        redis_url="redis://fake/0",
        agg_key_version=golden["agg_key_version"],
    )
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["schema_id"] == "tarka.counter_parity/v1"
    assert body["mode"] == "dual_diff"
    assert "matched" in body
    assert body["matched"] is True
    assert body["diffs"] == []
    assert artifact["matched"] is True


def test_dry_run_never_matched_proof(tmp_path, mod):
    out = tmp_path / "counter_parity_last.json"
    artifact = mod.run(mode="dry_run", out=out, fixture=_FIXTURE)
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["mode"] == "dry_run"
    assert body["matched"] is False
    assert mod.parity_matched(body) is False
    assert artifact["matched"] is False


def test_catalog_meta_dry_run_not_ok(mod, tmp_path, monkeypatch):
    from decision_api.internal_counters_api import _catalog_meta, _parity_health_ok

    dry = {
        "schema_id": "tarka.counter_parity/v1",
        "ts": "2026-08-05T00:00:00+00:00",
        "mode": "dry_run",
        "matched": False,
        "diffs": [],
    }
    assert _parity_health_ok(dry) is False

    legacy = {
        "schema_id": "tarka.counter_replay_job/v1",
        "generated_at": "2026-08-05T00:00:00+00:00",
        "ok": True,
        "mode": "dry_run",
    }
    assert _parity_health_ok(legacy) is False

    dual = {
        "schema_id": "tarka.counter_parity/v1",
        "ts": "2026-08-05T00:00:00+00:00",
        "mode": "dual_diff",
        "matched": True,
        "diffs": [],
    }
    assert _parity_health_ok(dual) is True

    report_path = tmp_path / "counter_parity_last.json"
    report_path.write_text(json.dumps(dual), encoding="utf-8")
    monkeypatch.setenv("COUNTER_PARITY_REPORT_PATH", str(report_path))
    meta = _catalog_meta()
    assert meta["last_parity_run"]["ok"] is True
    assert meta["last_parity_run"]["matched"] is True


def test_process_file_mismatch_produces_diffs(mod):
    process = {"entity_a": {"event_count_1h": 1}}
    golden = {
        "tenant_id": "t",
        "entities": {"entity_a": {"counters": {"event_count_1h": 2}}},
    }
    diffs = mod._compare_process_vs_file(process, golden)
    assert diffs
    assert diffs[0]["kind"] == "counter_mismatch"
