"""Gate: Rust evaluate panic → HTTP 200 + ``decision: REVIEW`` (fail-closed)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

_PKG_ROOT = Path(__file__).resolve().parents[1]
_PY_SRC = _PKG_ROOT / "python"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))

pytest.importorskip("tarka_rule_engine._native")

from tarka_rule_engine import PANIC_TEST_VELOCITY_SENTINEL, RuleEngine, create_evaluate_app  # noqa: E402


def test_rule_engine_evaluate_maps_rust_panic_to_review(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.CRITICAL, logger="tarka_rule_engine")
    eng = RuleEngine()
    out = eng.evaluate(0.1, PANIC_TEST_VELOCITY_SENTINEL)
    assert out["decision"] == "REVIEW"
    assert out.get("ok") is False
    assert any(
        r.levelno == logging.CRITICAL and "fail_closed_review" in r.message for r in caplog.records
    )


def test_post_v1_evaluate_returns_200_review_on_rust_panic() -> None:
    app = create_evaluate_app()
    with TestClient(app) as client:
        r = client.post(
            "/v1/evaluate",
            json={"graph_score": 0.25, "velocity_1h": PANIC_TEST_VELOCITY_SENTINEL},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["decision"] == "REVIEW"
    assert data.get("ok") is False
