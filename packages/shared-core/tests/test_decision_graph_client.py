"""Unit tests for decision graph fail-soft client."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_client():
    path = (
        Path(__file__).resolve().parents[1]
        / "tarka_shared"
        / "decision_graph_client.py"
    )
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
