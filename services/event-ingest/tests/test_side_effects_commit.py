"""Consumer POST to orchestrator side-effects: unset skip; only 2xx is ack-safe."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from event_ingest.config import settings
from event_ingest.main import _commit_evaluate_side_effects, _payload_for_decision_api


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"decision": "allow"}

    def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_side_effects_skip_when_url_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "orchestrator_url", "")
    http = AsyncMock()
    ok = await _commit_evaluate_side_effects(http, {"entity_id": "e1"}, _Resp(200))
    assert ok is True
    http.post.assert_not_called()


@pytest.mark.asyncio
async def test_side_effects_2xx_is_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "orchestrator_url", "http://orch.test")
    http = AsyncMock()
    http.post = AsyncMock(return_value=SimpleNamespace(status_code=200))
    ok = await _commit_evaluate_side_effects(http, {"entity_id": "e1"}, _Resp(200))
    assert ok is True


@pytest.mark.asyncio
async def test_side_effects_5xx_is_nak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "orchestrator_url", "http://orch.test")
    monkeypatch.setattr(settings, "orchestrator_internal_secret", "s3")
    http = AsyncMock()
    http.post = AsyncMock(return_value=SimpleNamespace(status_code=503))
    ok = await _commit_evaluate_side_effects(http, {"entity_id": "e1"}, _Resp(200))
    assert ok is False
    headers = http.post.await_args.kwargs["headers"]
    assert headers["x-internal-secret"] == "s3"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 409, 422, 499])
async def test_side_effects_non_2xx_is_nak(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    """A1: a 404 (drifted route / wrong base path) must NOT ack — only 2xx commits."""
    monkeypatch.setattr(settings, "orchestrator_url", "http://orch.test")
    http = AsyncMock()
    http.post = AsyncMock(return_value=SimpleNamespace(status_code=status_code))
    ok = await _commit_evaluate_side_effects(http, {"entity_id": "e1"}, _Resp(200))
    assert ok is False, f"status {status_code} must be treated as not-ack-safe"


def test_payload_unwraps_evaluate_request() -> None:
    out = _payload_for_decision_api(
        {
            "ingest_id": "x",
            "evaluate_request": {
                "tenant_id": "t",
                "entity_id": "e",
                "event_type": "login",
                "_ingest_id": "inner",
            },
        },
    )
    assert out["tenant_id"] == "t"
    assert "_ingest_id" not in out
    assert "evaluate_request" not in out
