"""Orchestrator gateway: rule engine + conditional Shadow hop (httpx mocked)."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orchestrator.main import create_app  # noqa: E402


class _DummyUpstreamResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _RoutingDummyAsyncClient:
    """Returns rule-engine vs shadow JSON based on URL; records every ``post``."""

    def __init__(
        self,
        evaluate_json: dict[str, object],
        analyze_json: dict[str, object],
    ) -> None:
        self._evaluate_json = evaluate_json
        self._analyze_json = analyze_json
        self.post_calls: list[tuple[str, dict[str, object], object]] = []

    async def __aenter__(self) -> _RoutingDummyAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        json: dict[str, object] | None = None,
        **kwargs: object,
    ) -> _DummyUpstreamResponse:
        headers = kwargs.get("headers")
        self.post_calls.append((url, json or {}, headers))
        if "/v1/evaluate" in url:
            return _DummyUpstreamResponse(self._evaluate_json)
        if "/v1/analyze" in url:
            return _DummyUpstreamResponse(self._analyze_json)
        raise AssertionError(f"unexpected post url: {url!r}")


class _TimeoutOnAnalyzeClient(_RoutingDummyAsyncClient):
    """Simulates Shadow ``/v1/analyze`` exceeding the orchestrator read deadline."""

    async def post(
        self,
        url: str,
        json: dict[str, object] | None = None,
        **kwargs: object,
    ) -> _DummyUpstreamResponse:
        headers = kwargs.get("headers")
        self.post_calls.append((url, json or {}, headers))
        if "/v1/evaluate" in url:
            return _DummyUpstreamResponse(self._evaluate_json)
        if "/v1/analyze" in url:
            req = httpx.Request("POST", url)
            raise httpx.ReadTimeout("shadow analyze deadline", request=req)
        raise AssertionError(f"unexpected post url: {url!r}")


def test_ingest_shadow_review_triggers_shadow_downstream_and_logs(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate: SHADOW_REVIEW → POST /v1/analyze; log line proves downstream scheduling."""
    caplog.set_level(logging.INFO, logger="orchestrator.main")
    rule_engine_body: dict[str, object] = {
        "actions": ["SHADOW_REVIEW", "FLAG"],
        "transaction_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    }
    shadow_body: dict[str, object] = {
        "transaction_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "risk_score": 1.0,
        "is_fraud": False,
        "reasoning": ["mock"],
        "confidence_metrics": {},
        "_debug": {"audit_log_id": 1},
    }
    dummy = _RoutingDummyAsyncClient(rule_engine_body, shadow_body)

    def _client_factory(*args: object, **kwargs: object) -> _RoutingDummyAsyncClient:
        return dummy

    monkeypatch.setattr("orchestrator.main.httpx.AsyncClient", _client_factory)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url="http://shadow.test",
        shadow_api_key="unit-test-token",
    )
    body = {
        "entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "amount": 500.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"channel": "wire"},
    }

    with TestClient(app) as client:
        response = client.post("/v1/ingest", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["rule_engine"] == rule_engine_body
    assert data["shadow_agent"] == shadow_body
    assert len(dummy.post_calls) == 2
    ev_url, ev_body, _ = dummy.post_calls[0]
    sh_url, sh_body, sh_headers = dummy.post_calls[1]
    assert ev_url == "http://rules.test/v1/evaluate"
    assert sh_url == "http://shadow.test/v1/analyze"
    assert sh_headers == {"X-Shadow-Token": "unit-test-token"}
    assert ev_body == sh_body

    log_text = " ".join(r.message for r in caplog.records)
    assert "orchestrator_shadow_downstream_post" in log_text
    assert "http://shadow.test/v1/analyze" in log_text
    assert "SHADOW_REVIEW" in log_text


def test_ingest_allow_only_skips_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    rule_engine_body: dict[str, object] = {
        "actions": ["ALLOW"],
        "transaction_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    }
    dummy = _RoutingDummyAsyncClient(rule_engine_body, {})

    monkeypatch.setattr("orchestrator.main.httpx.AsyncClient", lambda *a, **k: dummy)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url="http://shadow.test",
        shadow_api_key="unit-test-token",
    )
    body = {
        "entity_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "amount": 10.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {},
    }
    with TestClient(app) as client:
        response = client.post("/v1/ingest", json=body)
    assert response.status_code == 200
    assert "shadow_agent" not in response.json()
    assert len(dummy.post_calls) == 1


def test_ingest_shadow_analyze_timeout_returns_flag_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate: Shadow read deadline → HTTP 200 + ``FLAG`` fallback (no orchestrator 5xx)."""
    rule_engine_body: dict[str, object] = {
        "actions": ["SHADOW_REVIEW"],
        "transaction_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
    }
    dummy = _TimeoutOnAnalyzeClient(rule_engine_body, {})

    monkeypatch.setattr("orchestrator.main.httpx.AsyncClient", lambda *a, **k: dummy)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url="http://shadow.test",
        shadow_api_key="unit-test-token",
        shadow_analyze_timeout_seconds=3.0,
    )
    body = {
        "entity_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "amount": 500.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"channel": "wire"},
    }
    with TestClient(app) as client:
        response = client.post("/v1/ingest", json=body)

    assert response.status_code == 200
    data = response.json()
    assert data["rule_engine"] == rule_engine_body
    assert "shadow_agent" not in data
    assert data.get("orchestrator_fallback_decision") == "FLAG"
    assert data.get("orchestrator_fallback_reason") == "shadow_analyze_deadline_exceeded"
    assert float(data.get("orchestrator_shadow_deadline_seconds", 0)) == 3.0
    assert len(dummy.post_calls) == 2


def test_ingest_block_only_skips_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    rule_engine_body: dict[str, object] = {
        "actions": ["BLOCK"],
        "transaction_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
    }
    dummy = _RoutingDummyAsyncClient(rule_engine_body, {})

    monkeypatch.setattr("orchestrator.main.httpx.AsyncClient", lambda *a, **k: dummy)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url="http://shadow.test",
    )
    body = {
        "entity_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "amount": 999.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {},
    }
    with TestClient(app) as client:
        response = client.post("/v1/ingest", json=body)
    assert response.status_code == 200
    assert "shadow_agent" not in response.json()
    assert len(dummy.post_calls) == 1
