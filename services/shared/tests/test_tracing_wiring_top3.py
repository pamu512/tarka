from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[3]
    return (root / path).read_text(encoding="utf-8")


def test_decision_api_wiring_present():
    text = _read("services/decision-api/src/decision_api/main.py")
    assert "from tarka_shared.tracing import setup_tracing" in text
    assert 'setup_tracing(app, "decision-api")' in text


def test_case_api_wiring_present():
    text = _read("services/case-api/src/case_api/main.py")
    assert "from tarka_shared.tracing import setup_tracing" in text
    assert 'setup_tracing(app, "case-api")' in text


def test_investigation_agent_wiring_present():
    text = _read("services/investigation-agent/src/investigation_agent/main.py")
    assert "from tarka_shared.tracing import setup_tracing" in text
    assert 'setup_tracing(app, "investigation-agent")' in text
