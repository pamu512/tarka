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


def test_openapi_spec_and_redoc_at_docs() -> None:
    """Gate: OpenAPI JSON and ReDoc UI are served; Swagger UI is not the default at /docs."""
    app = create_app(rule_engine_url="http://rules.test", shadow_agent_url=None)
    with TestClient(app) as client:
        spec_r = client.get("/openapi.json")
        assert spec_r.status_code == 200
        spec = spec_r.json()
        assert spec["openapi"].startswith("3.")
        assert "/v1/ingest" in spec["paths"]
        assert "/v1/ingest/chargeback" in spec["paths"]
        assert "/v1/investigation/prime" in spec["paths"]
        assert "/v1/rules/shadow-test" in spec["paths"]
        assert "/v1/analytics/velocity" in spec["paths"]
        assert "/v1/analytics/transactions" in spec["paths"]
        assert "/v1/cases/{case_id}/status" in spec["paths"]
        assert "/v1/cases/{case_id}/export" in spec["paths"]
        assert "/v1/cases/{case_id}/file-dispute" in spec["paths"]
        assert "/v1/ai/feedback" in spec["paths"]
        desc = spec["info"].get("description", "")
        assert "8778" not in desc
        assert "/v1/evaluate" not in desc
        docs_r = client.get("/docs")
        assert docs_r.status_code == 200
        body = docs_r.content.lower()
        assert b"redoc" in body


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


class _ConnectErrorOnAnalyzeClient(_RoutingDummyAsyncClient):
    """Simulates Shadow sidecar gone (``kill -9`` / connection refused)."""

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
            raise httpx.ConnectError("connection refused", request=req)
        raise AssertionError(f"unexpected post url: {url!r}")


def test_ingest_shadow_review_triggers_shadow_downstream_and_logs(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate: SHADOW_REVIEW → POST /v1/analyze; log line proves downstream scheduling."""
    caplog.set_level(logging.INFO, logger="orchestrator.transaction_ingest")
    rule_engine_body: dict[str, object] = {
        "actions": ["SHADOW_REVIEW", "FLAG"],
        "transaction_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "evaluation_trace": [],
        "blocking_rule_id": None,
    }
    shadow_body: dict[str, object] = {
        "transaction_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "risk_score": 1.0,
        "is_fraud": False,
        "reasoning": ["mock"],
        "confidence_metrics": {},
        "ai_reasoning": "mock narrative",
        "_debug": {"audit_log_id": 1},
    }
    dummy = _RoutingDummyAsyncClient(rule_engine_body, shadow_body)

    def _client_factory(*args: object, **kwargs: object) -> _RoutingDummyAsyncClient:
        return dummy

    monkeypatch.setattr("orchestrator.transaction_ingest.httpx.AsyncClient", _client_factory)

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
    assert sh_body == {"transaction": ev_body}

    log_text = " ".join(r.message for r in caplog.records)
    assert "orchestrator_shadow_downstream_post" in log_text  # logger name still orchestrator.*
    assert "http://shadow.test/v1/analyze" in log_text
    assert "SHADOW_REVIEW" in log_text


def test_ingest_allow_only_skips_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    rule_engine_body: dict[str, object] = {
        "actions": ["ALLOW"],
        "transaction_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "evaluation_trace": [],
        "blocking_rule_id": None,
    }
    dummy = _RoutingDummyAsyncClient(rule_engine_body, {})

    monkeypatch.setattr("orchestrator.transaction_ingest.httpx.AsyncClient", lambda *a, **k: dummy)

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
        "evaluation_trace": [],
        "blocking_rule_id": None,
    }
    dummy = _TimeoutOnAnalyzeClient(rule_engine_body, {})

    monkeypatch.setattr("orchestrator.transaction_ingest.httpx.AsyncClient", lambda *a, **k: dummy)

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


def test_ingest_shadow_connect_error_returns_flag_sidescar_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate: Shadow transport failure → HTTP 200 + ``FLAG`` + ``SIDECAR_UNREACHABLE`` (no 503)."""
    rule_engine_body: dict[str, object] = {
        "actions": ["SHADOW_REVIEW"],
        "transaction_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        "evaluation_trace": [],
        "blocking_rule_id": None,
    }
    dummy = _ConnectErrorOnAnalyzeClient(rule_engine_body, {})

    monkeypatch.setattr("orchestrator.transaction_ingest.httpx.AsyncClient", lambda *a, **k: dummy)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url="http://shadow.test",
        shadow_api_key="unit-test-token",
    )
    body = {
        "entity_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
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
    assert data.get("orchestrator_fallback_reason") == "SIDECAR_UNREACHABLE"
    assert "orchestrator_shadow_deadline_seconds" not in data
    assert len(dummy.post_calls) == 2


def test_health_full_returns_aggregate_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /health/full probes rule engine /health and Shadow /health/db."""

    class _HealthFullClient:
        async def __aenter__(self) -> _HealthFullClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> object:
            class _Resp:
                status_code = 200
                text = ""

            if url.endswith("/health") and "rules.test" in url:
                return _Resp()
            if "/health/db" in url:
                return _Resp()
            raise AssertionError(f"unexpected GET {url!r}")

    monkeypatch.setattr("orchestrator.transaction_ingest.httpx.AsyncClient", lambda *a, **k: _HealthFullClient())

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url="http://shadow.test",
        shadow_api_key="unit-test-token",
    )
    with TestClient(app) as client:
        response = client.get("/health/full")

    assert response.status_code == 200
    data = response.json()
    assert "services" in data
    names = {row["component"]: row["status"] for row in data["services"]}
    assert names.get("orchestrator") == "ok"
    assert names.get("rule_engine") == "ok"
    assert names.get("shadow_agent") == "ok"


def test_health_full_shadow_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    class _RuleOnlyClient:
        async def __aenter__(self) -> _RuleOnlyClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> object:
            class _Resp:
                status_code = 200
                text = ""

            if url.endswith("/health"):
                return _Resp()
            raise AssertionError(f"unexpected GET {url!r}")

    monkeypatch.setattr("orchestrator.transaction_ingest.httpx.AsyncClient", lambda *a, **k: _RuleOnlyClient())

    app = create_app(rule_engine_url="http://rules.test", shadow_agent_url=None)
    with TestClient(app) as client:
        response = client.get("/health/full")

    assert response.status_code == 200
    data = response.json()
    shadow_rows = [r for r in data["services"] if r["component"] == "shadow_agent"]
    assert len(shadow_rows) == 1
    assert shadow_rows[0]["status"] == "not_configured"


def test_demo_simulate_attack_returns_full_results_array() -> None:
    """Gate: demo endpoint returns ``total`` and a ``results`` array of that length."""
    app = create_app(rule_engine_url="http://rules.test", shadow_agent_url="http://shadow.test")
    with TestClient(app) as client:
        response = client.post("/v1/demo/simulate_attack", json={})
    assert response.status_code == 200
    data = response.json()
    assert data.get("total") == 5
    assert len(data.get("results", [])) == 5
    rows = data["results"]
    assert rows[0]["pattern_index"] == 0
    assert rows[-1]["pattern_index"] == 4
    assert rows[0]["total"] == 5


def test_ingest_block_only_skips_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    rule_engine_body: dict[str, object] = {
        "actions": ["BLOCK"],
        "transaction_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "evaluation_trace": [
            {
                "rule_id": "00000000-0000-0000-0000-00000000c0de",
                "rule_name": "demo",
                "priority": 5,
                "matched": True,
                "action": "BLOCK",
            },
        ],
        "blocking_rule_id": "00000000-0000-0000-0000-00000000c0de",
    }
    dummy = _RoutingDummyAsyncClient(rule_engine_body, {})

    monkeypatch.setattr("orchestrator.transaction_ingest.httpx.AsyncClient", lambda *a, **k: dummy)

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
