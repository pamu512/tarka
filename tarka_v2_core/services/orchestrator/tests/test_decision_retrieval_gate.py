"""Gate: GET /v1/decisions/{transaction_id} returns audit-backed decision detail."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


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


def test_get_decision_detail_after_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    import orchestrator.models.cases  # noqa: F401, PLC0415
    import orchestrator.models.decision  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from orchestrator.main import create_app

    entity = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    rule_engine_body: dict[str, object] = {
        "actions": ["FLAG"],
        "transaction_id": entity,
        "evaluation_trace": [
            {
                "rule_id": "00000000-0000-0000-0000-00000000c0df",
                "rule_name": "demo_flag",
                "matched": True,
                "priority": 10,
                "action": "FLAG",
            }
        ],
        "blocking_rule_id": None,
    }

    def _client_factory(*args: object, **kwargs: object) -> _EvalOnlyAsyncClient:
        return _EvalOnlyAsyncClient(rule_engine_body)

    monkeypatch.setattr("orchestrator.transaction_ingest.httpx.AsyncClient", _client_factory)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
    )
    ingest_body = {
        "entity_id": entity,
        "amount": 500.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"channel": "wire", "merchant_id": "merch-gate"},
    }

    with TestClient(app) as client:
        missing = client.get(f"/v1/decisions/{entity}")
        assert missing.status_code == 404

        ingest = client.post("/v1/ingest", json=ingest_body)
        assert ingest.status_code == 200

        detail = client.get(f"/v1/decisions/{entity}")
        assert detail.status_code == 200
        data = detail.json()
        assert data["transaction_schema"]["transaction_id"] == entity
        assert data["transaction_schema"]["amount_cents"] == 50000
        assert data["transaction_schema"]["channel"] == "wire"
        assert data["shadow_decision"]["model_id"] == "shadow-agent"
        assert isinstance(data.get("evaluation_trace"), list)
        assert len(data["evaluation_trace"]) == 1


def test_get_decision_detail_invalid_uuid() -> None:
    import orchestrator.models.cases  # noqa: F401, PLC0415
    import orchestrator.models.decision  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415

    from orchestrator.main import create_app

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
    )
    with TestClient(app) as client:
        r = client.get("/v1/decisions/not-a-uuid")
        assert r.status_code == 422
