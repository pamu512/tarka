"""Gate: a REVIEW policy outcome publishes ``session_id`` + ``trace`` to NATS ``shadow.investigate``."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

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


class _EvalOnlyAsyncClient:
    def __init__(self, evaluate_json: dict[str, object]) -> None:
        self._evaluate_json = evaluate_json

    async def __aenter__(self) -> _EvalOnlyAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        json: dict[str, object] | None = None,
        **kwargs: object,
    ) -> _DummyUpstreamResponse:
        if "/v1/evaluate" in url:
            return _DummyUpstreamResponse(self._evaluate_json)
        raise AssertionError(f"unexpected post url: {url!r}")


def test_v1_ingest_review_triggers_shadow_investigate_nats_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    txn_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    trace = [{"rule_id": "r1", "matched": True}]
    rule_engine_body: dict[str, object] = {
        "actions": ["REVIEW"],
        "transaction_id": txn_id,
        "evaluation_trace": trace,
        "decision": "REVIEW",
    }

    mock_nc = AsyncMock()
    mock_nc.publish = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "orchestrator.transaction_ingest.httpx.AsyncClient",
        lambda *a, **k: _EvalOnlyAsyncClient(rule_engine_body),
    )

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        shadow_dispatch_nats_client=mock_nc,
    )
    body = {
        "entity_id": txn_id,
        "amount": 12.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"session_id": "sess-gate-99"},
    }
    with TestClient(app) as client:
        r = client.post("/v1/ingest", json=body)

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["rule_engine"]["decision"] == "REVIEW"

    mock_nc.publish.assert_awaited_once()
    (subject, raw), _kw = mock_nc.publish.await_args
    assert subject == "shadow.investigate"
    payload = json.loads(raw.decode("utf-8"))
    assert payload["session_id"] == "sess-gate-99"
    assert payload["trace"] == trace


def test_review_decision_via_decision_field_only_still_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``decision: REVIEW`` without an ``actions`` entry still counts as Review."""
    txn_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    rule_engine_body: dict[str, object] = {
        "actions": ["FLAG"],
        "transaction_id": txn_id,
        "evaluation_trace": [],
        "decision": "REVIEW",
    }
    mock_nc = AsyncMock()
    mock_nc.publish = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "orchestrator.transaction_ingest.httpx.AsyncClient",
        lambda *a, **k: _EvalOnlyAsyncClient(rule_engine_body),
    )
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        shadow_dispatch_nats_client=mock_nc,
    )
    body = {
        "entity_id": txn_id,
        "amount": 5.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {},
    }
    with TestClient(app) as client:
        r = client.post("/v1/ingest", json=body)
    assert r.status_code == 200
    mock_nc.publish.assert_awaited_once()
    _sub, raw = mock_nc.publish.await_args[0]
    assert json.loads(raw.decode("utf-8"))["session_id"] == txn_id
