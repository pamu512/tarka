"""Tests for ``tarka import-rules`` (validation, SQLite persistence, rule-engine reload)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (
    _ROOT / "services" / "rule_engine" / "src",
    _ROOT / "services" / "ingestor" / "src",
    _ROOT / "services" / "shared",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from starlette.testclient import TestClient  # noqa: E402

from tarka_v2_core.rules_import import ImportRulesError, run_import_rules  # noqa: E402


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "import_rules_flag_metadata.json"


def test_run_import_rules_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ImportRulesError, match="Invalid JSON"):
        run_import_rules(bad, skip_reload=True)


def test_run_import_rules_sqlite_and_evaluate_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "rules.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("SHADOW_DATABASE_URL", url)
    monkeypatch.setenv("TARKA_SKIP_RULE_RELOAD", "1")

    n, err = run_import_rules(FIXTURE, skip_reload=True)
    assert n == 1
    assert err is None

    from rule_engine.main import create_app

    body = {
        "entity_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "amount": 12.34,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"note": "CLI_IMPORT_FLAG_MARKER"},
    }
    with TestClient(create_app()) as client:
        assert client.post("/v1/rules/reload").json() == {"ok": True, "count": 1}
        r = client.post("/v1/evaluate", json=body)
    assert r.status_code == 200
    assert r.json()["actions"] == ["FLAG"]


def test_reload_webhook_called(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "rules2.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("SHADOW_DATABASE_URL", url)
    monkeypatch.delenv("TARKA_SKIP_RULE_RELOAD", raising=False)
    monkeypatch.setenv("RULE_ENGINE_URL", "http://rule-engine.invalid.example")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    inner = MagicMock()
    inner.post.return_value = mock_resp
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = inner
    mock_ctx.__exit__.return_value = None

    with patch("tarka_v2_core.rules_import.httpx.Client", return_value=mock_ctx):
        _, err = run_import_rules(FIXTURE, skip_reload=False)
    assert err is None
    inner.post.assert_called_once()
    called_url = inner.post.call_args[0][0]
    assert "/v1/rules/reload" in called_url
