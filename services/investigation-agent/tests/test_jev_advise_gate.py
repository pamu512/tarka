"""S3: investigation-agent residual review gate. Empty URL matches today's Advise path."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from investigation_agent import config
from investigation_agent.main import app
from jev_system_one.client import SystemOneJudgment

_SECRET = "jev-secret-should-not-leak"
_CASE = {
    "id": "case-1",
    "tenant_id": "demo",
    "entity_id": "ent-1",
    "trace_id": "11111111-1111-1111-1111-111111111111",
    "email": "person@example.com",
    "title": "Jane Doe",
}
_AUDIT = {
    "ml_summary": "BAIT_ML_SUMMARY",
    "recommended_action": "deny the payout",
    "pack_id": "fintech",
    "rule_hits": ["velocity_burst"],
    "event_type": "card_payment",
    "amount": 80,
}


class _RecordingClient:
    """Stands in for SystemOneClient. Counts real judge attempts."""

    constructed = 0
    bodies: list[dict[str, Any]] = []
    result = SystemOneJudgment(answers=None, latency_ms=0, error="http")

    def __init__(self, **kwargs: Any) -> None:
        type(self).constructed += 1
        self.kwargs = kwargs

    async def judge(self, body: dict[str, Any]) -> SystemOneJudgment:
        type(self).bodies.append(body)
        secret = str(self.kwargs.get("api_key") or "")
        if secret and secret in json.dumps(body):
            raise AssertionError("api key leaked into the System One body")
        return type(self).result


def _chat(**extra: object) -> dict:
    body: dict[str, Any] = {
        "tenant_id": "demo",
        "analyst_id": "analyst-1",
        "messages": [{"role": "user", "content": "review this residual case"}],
    }
    body.update(extra)
    return body


def _enable_jev(monkeypatch, *, mode: str, url: str = "http://jev.test") -> None:
    monkeypatch.setattr(config.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(config.settings, "copilot_plain_chat", True)
    monkeypatch.setattr(config.settings, "jev_system_one_url", url)
    monkeypatch.setattr(config.settings, "jev_mode", mode)
    monkeypatch.setattr(config.settings, "jev_api_key", _SECRET)
    monkeypatch.setattr(config.settings, "jev_min_confidence", 0.55)
    monkeypatch.setattr(config.settings, "jev_timeout_ms", 400)
    monkeypatch.setattr(config.settings, "jev_question_pack", "advise_sufficiency_v1")
    monkeypatch.setattr(config.settings, "graph_service_url", "")
    _RecordingClient.constructed = 0
    _RecordingClient.bodies = []
    monkeypatch.setattr("investigation_agent.jev_gate.SystemOneClient", _RecordingClient)


def _low_confidence() -> SystemOneJudgment:
    return SystemOneJudgment(
        answers={
            "has_enough_signal": {"value": False, "confidence": 0.2},
            "review_priority": {"value": "skip_noise", "confidence": 0.4},
            "pattern_hint": {"value": "velocity", "confidence": 0.9},
        },
        latency_ms=18,
        error=None,
    )


def _post(payload: dict, *, case_found: bool, fetches: list[str] | None = None) -> tuple[Any, bool]:
    case_result = {"case": _CASE} if case_found else {"error": "not_found"}

    async def _case(*_a, **_k):
        if fetches is not None:
            fetches.append("case")
        return case_result

    async def _audit(*_a, **_k):
        if fetches is not None:
            fetches.append("audit")
        return {"audit": _AUDIT}

    llm = AsyncMock(return_value=("analyst note", [], {}, 1))
    with patch("investigation_agent.jev_gate.tool_get_case", new=_case):
        with patch("investigation_agent.jev_gate.tool_get_decision_audit", new=_audit):
            with patch("investigation_agent.main._llm_tool_loop", new=llm):
                with TestClient(app) as client:
                    response = client.post("/v1/chat", json=payload)
    return response, llm.called


def test_empty_url_does_not_call_jev_and_still_calls_llm(monkeypatch) -> None:
    _enable_jev(monkeypatch, mode="shadow", url="")
    fetches: list[str] = []
    response, llm_called = _post(_chat(case_id="case-1"), case_found=True, fetches=fetches)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "jev" not in body
    assert llm_called
    assert body["reply"] == "analyst note"
    assert fetches == []
    assert _RecordingClient.constructed == 0
    assert _SECRET not in response.text


def test_mode_off_and_chat_without_case_skip_the_gate(monkeypatch) -> None:
    _enable_jev(monkeypatch, mode="off", url="http://jev.test")
    fetches: list[str] = []
    response, llm_called = _post(_chat(case_id="case-1"), case_found=True, fetches=fetches)
    assert response.status_code == 200, response.text
    assert llm_called
    assert fetches == []
    assert "jev" not in response.json()
    assert _RecordingClient.constructed == 0

    _enable_jev(monkeypatch, mode="gate")
    fetches = []
    response, llm_called = _post(_chat(), case_found=False, fetches=fetches)
    assert llm_called
    assert fetches == []
    assert "jev" not in response.json()
    assert _RecordingClient.constructed == 0


def test_thin_evidence_abstains_with_zero_jev_and_zero_llm(monkeypatch) -> None:
    _enable_jev(monkeypatch, mode="gate")
    response, llm_called = _post(_chat(case_id="case-missing"), case_found=False)
    assert response.status_code == 200, response.text
    body = response.json()
    assert llm_called is False
    assert _RecordingClient.constructed == 0
    assert body["tool_calls"] == []
    assert body["jev"]["gate"] == "thin_evidence"
    assert body["jev"]["answers"] is None
    assert body["jev"]["llm_invoked"] is False
    assert "too thin" in body["reply"]
    assert "Promote" not in response.text
    assert _SECRET not in response.text


def test_low_confidence_gate_skips_llm(monkeypatch) -> None:
    _enable_jev(monkeypatch, mode="gate")
    _RecordingClient.result = _low_confidence()
    response, llm_called = _post(_chat(case_id="case-1"), case_found=True)
    assert response.status_code == 200, response.text
    assert llm_called is False
    assert _RecordingClient.constructed == 1
    sent = _RecordingClient.bodies[0]
    body = response.json()
    assert body["jev"]["gate"] == "abstain"
    assert body["jev"]["llm_invoked"] is False
    assert body["jev"]["answers"]["has_enough_signal"]["value"] is False
    assert body["jev"]["answers"]["has_enough_signal"]["confidence"] == 0.2
    assert "withheld" in body["reply"]
    assert sent["evidence"]["receipt"]["why"] == "velocity_burst"
    raw = json.dumps(sent)
    assert "BAIT_ML_SUMMARY" not in raw
    assert "person@example.com" not in raw
    assert "Jane Doe" not in raw
    assert _SECRET not in response.text
    assert _SECRET not in raw


def test_low_confidence_shadow_still_calls_llm(monkeypatch) -> None:
    _enable_jev(monkeypatch, mode="shadow")
    _RecordingClient.result = _low_confidence()
    response, llm_called = _post(_chat(case_id="case-1"), case_found=True)
    assert response.status_code == 200, response.text
    assert llm_called is True
    body = response.json()
    assert body["reply"] == "analyst note"
    assert body["jev"]["gate"] == "abstain"
    assert body["jev"]["llm_invoked"] is True
    assert body["jev"]["answers"]["review_priority"]["value"] == "skip_noise"
    assert _SECRET not in response.text


def test_timeout_and_malformed_follow_mode(monkeypatch) -> None:
    errors = ("timeout", "schema")
    for error in errors:
        for mode, expect_llm in (("shadow", True), ("gate", False)):
            _enable_jev(monkeypatch, mode=mode)
            _RecordingClient.result = SystemOneJudgment(answers=None, latency_ms=400, error=error)
            response, llm_called = _post(_chat(case_id="case-1"), case_found=True)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["jev"]["gate"] == "jev_error"
            assert body["jev"]["answers"] is None
            assert body["jev"]["llm_invoked"] is expect_llm
            assert llm_called is expect_llm
            if not expect_llm:
                assert "failed closed" in body["reply"]
            assert _SECRET not in response.text
