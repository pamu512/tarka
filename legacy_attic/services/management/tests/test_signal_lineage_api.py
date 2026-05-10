"""GET /signals/impact HTTP surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tarka_management.app import create_app
from tarka_management.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_signals_impact_503_when_rules_root_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TARKA_MANAGEMENT_YAML_RULES_ROOT", "/nonexistent/tarka/rules/root")
    reset_settings_cache()
    client = TestClient(create_app())
    r = client.get("/signals/impact")
    assert r.status_code == 503
    assert r.json()["detail"]["reason_code"] == "LINEAGE_RULES_ROOT_UNAVAILABLE"


def test_signals_impact_returns_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "yaml"
    root.mkdir()
    (root / "rules.yaml").write_text(
        """
version: 1
rules:
  - id: r1
    expression:
      kind: compare_signal
      signal_name: velocity_1h
      op: gte
      expected: 10
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TARKA_MANAGEMENT_YAML_RULES_ROOT", str(root))
    reset_settings_cache()

    client = TestClient(create_app())
    r = client.get("/signals/impact")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scan_summary"]["signal_count"] == 1
    assert "velocity_1h" in body["impact_by_signal"]

    r2 = client.get("/signals/impact", params={"signal": "velocity_1h"})
    assert r2.status_code == 200
    filt = r2.json()["filter"]
    assert filt["matched"] is True
    assert filt["rule_count"] == 1


def test_optional_api_key_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "yaml"
    root.mkdir()
    (root / "x.yaml").write_text(
        "version: 1\nrules: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TARKA_MANAGEMENT_YAML_RULES_ROOT", str(root))
    monkeypatch.setenv("TARKA_MANAGEMENT_API_KEY", "k9")
    reset_settings_cache()

    client = TestClient(create_app())
    assert client.get("/signals/impact").status_code == 401
    ok = client.get("/signals/impact", headers={"x-api-key": "k9"})
    assert ok.status_code == 200
