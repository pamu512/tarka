"""Unit tests for decision graph fail-soft client."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_client():
    path = Path(__file__).resolve().parents[1] / "tarka_shared" / "decision_graph_client.py"
    spec = importlib.util.spec_from_file_location("decision_graph_client", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_record_disabled_returns_none(monkeypatch) -> None:
    mod = _load_client()
    monkeypatch.setenv("DECISION_GRAPH_ENABLED", "0")
    monkeypatch.setenv("GRAPH_SERVICE_URL", "http://example.invalid")
    assert mod.record_decision_failsoft({"tenant_id": "t", "kind": "evaluate"}) is None


def test_record_no_url_returns_none(monkeypatch) -> None:
    mod = _load_client()
    monkeypatch.setenv("DECISION_GRAPH_ENABLED", "1")
    monkeypatch.delenv("GRAPH_SERVICE_URL", raising=False)
    monkeypatch.delenv("DECISION_GRAPH_URL", raising=False)
    assert mod.record_decision_failsoft({"tenant_id": "t", "kind": "evaluate"}) is None


def test_invalidate_disabled_returns_none(monkeypatch) -> None:
    mod = _load_client()
    monkeypatch.setenv("DECISION_GRAPH_ENABLED", "0")
    assert mod.invalidate_decision_failsoft("t1", "dec_1", reason="x", supersede_to="dec_2") is None


def test_resolve_disposition_to_supersede_uses_latest_human(monkeypatch) -> None:
    mod = _load_client()

    def fake_latest(tenant_id, **kwargs):
        assert tenant_id == "t1"
        assert kwargs.get("kind") == "human_disposition"
        assert kwargs.get("case_id") == "case-9"
        return {"external_id": "dec_old_disp"}

    monkeypatch.setattr(mod, "find_latest_failsoft", fake_latest)
    assert mod.resolve_disposition_to_supersede("t1", "case-9") == "dec_old_disp"
