from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from decision_api import evaluate_idempotency as idem
from tarka_core.cache import LocalDictCache


@pytest.fixture(autouse=True)
def _local_idempotency_store(monkeypatch: pytest.MonkeyPatch):
    cache = LocalDictCache()

    async def _connect() -> None:
        return None

    monkeypatch.setattr(idem.redis_tags, "connect", _connect)
    monkeypatch.setattr(idem.redis_tags, "_client", None)
    monkeypatch.setattr(idem.redis_tags, "_kv", cache)
    yield cache


def _fingerprint(entity_id: str, amount: int) -> str:
    return idem.canonical_request_fingerprint(
        {
            "tenant_id": "t1",
            "event_type": "payment",
            "entity_id": entity_id,
            "payload": {"amount": amount},
        }
    )


def _request_payload() -> dict:
    return {
        "tenant_id": "t1",
        "event_type": "payment",
        "entity_id": "entity-1",
        "payload": {"amount": 100},
    }


def _allow_response():
    from decision_api.schemas import EvaluateResponse

    return EvaluateResponse(
        trace_id=uuid4(),
        decision="allow",
        score=0.0,
        tags=[],
        inference_context={},
    )


@pytest.fixture
async def endpoint_client(monkeypatch: pytest.MonkeyPatch):
    from decision_api.main import app, get_session

    cache = LocalDictCache()
    store = SimpleNamespace(
        connect=AsyncMock(),
        _client=None,
        _kv=cache,
        _async_lock=asyncio.Lock(),
    )
    monkeypatch.setattr(idem, "redis_tags", store)
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"test-key":["t1"]}')
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)

    async def _session_override():
        yield None

    app.dependency_overrides[get_session] = _session_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"x-api-key": "test-key"},
    ) as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_same_key_different_payload_conflicts_without_returning_old_decision():
    first_fp = _fingerprint("entity-1", 100)
    second_fp = _fingerprint("entity-2", 900)
    first = await idem.claim_evaluate_idempotency(
        tenant_id="t1",
        idempotency_key="same-key",
        request_fingerprint=first_fp,
    )
    assert first.state == "owned"
    await idem.complete_evaluate_idempotency(
        tenant_id="t1",
        idempotency_key="same-key",
        request_fingerprint=first_fp,
        owner_token=first.owner_token or "",
        response={"decision": "allow", "entity_id": "entity-1"},
    )

    mismatch = await idem.claim_evaluate_idempotency(
        tenant_id="t1",
        idempotency_key="same-key",
        request_fingerprint=second_fp,
    )

    assert mismatch.state == "mismatch"
    assert mismatch.response is None


@pytest.mark.asyncio
async def test_concurrent_same_request_has_one_owner_and_one_in_flight():
    fp = _fingerprint("entity-1", 100)
    claims = await asyncio.gather(
        *(
            idem.claim_evaluate_idempotency(
                tenant_id="t1",
                idempotency_key="concurrent-key",
                request_fingerprint=fp,
            )
            for _ in range(2)
        )
    )

    assert sorted(claim.state for claim in claims) == ["in_flight", "owned"]


@pytest.mark.asyncio
async def test_failed_owner_release_allows_immediate_retry():
    fp = _fingerprint("entity-1", 100)
    first = await idem.claim_evaluate_idempotency(
        tenant_id="t1",
        idempotency_key="retry-key",
        request_fingerprint=fp,
    )
    assert first.state == "owned"

    released = await idem.release_evaluate_idempotency(
        tenant_id="t1",
        idempotency_key="retry-key",
        request_fingerprint=fp,
        owner_token=first.owner_token or "",
    )
    retry = await idem.claim_evaluate_idempotency(
        tenant_id="t1",
        idempotency_key="retry-key",
        request_fingerprint=fp,
    )

    assert released is True
    assert retry.state == "owned"


@pytest.mark.asyncio
async def test_only_owner_can_renew_in_flight_lease():
    fingerprint = _fingerprint("entity-1", 100)
    claim = await idem.claim_evaluate_idempotency(
        tenant_id="t1",
        idempotency_key="renew-key",
        request_fingerprint=fingerprint,
        lease_seconds=1,
    )

    assert (
        await idem.renew_evaluate_idempotency(
            tenant_id="t1",
            idempotency_key="renew-key",
            request_fingerprint=fingerprint,
            owner_token="not-the-owner",
            lease_seconds=1,
        )
        is False
    )
    assert (
        await idem.renew_evaluate_idempotency(
            tenant_id="t1",
            idempotency_key="renew-key",
            request_fingerprint=fingerprint,
            owner_token=claim.owner_token or "",
            lease_seconds=1,
        )
        is True
    )


@pytest.mark.asyncio
async def test_endpoint_exception_releases_claim_for_immediate_retry(endpoint_client):
    with patch(
        "decision_api.main._evaluate_decision_impl",
        new=AsyncMock(
            side_effect=[RuntimeError("evaluation failed"), _allow_response()]
        ),
    ) as evaluator:
        with pytest.raises(RuntimeError, match="evaluation failed"):
            await endpoint_client.post(
                "/v1/decisions/evaluate",
                headers={"Idempotency-Key": "endpoint-retry"},
                json=_request_payload(),
            )
        retried = await endpoint_client.post(
            "/v1/decisions/evaluate",
            headers={"Idempotency-Key": "endpoint-retry"},
            json=_request_payload(),
        )

    assert retried.status_code == 200, retried.text
    assert evaluator.await_count == 2


@pytest.mark.asyncio
async def test_endpoint_renews_lease_during_long_evaluation(
    endpoint_client, monkeypatch
):
    monkeypatch.setenv("TARKA_EVALUATE_IDEMPOTENCY_LEASE_SECONDS", "1")
    monkeypatch.setenv("TARKA_EVALUATE_IDEMPOTENCY_HEARTBEAT_SECONDS", "0.2")
    started = asyncio.Event()
    finish = asyncio.Event()

    async def _slow_evaluation(*_args, **_kwargs):
        started.set()
        await finish.wait()
        return _allow_response()

    with patch(
        "decision_api.main._evaluate_decision_impl",
        new=AsyncMock(side_effect=_slow_evaluation),
    ) as evaluator:
        first = asyncio.create_task(
            endpoint_client.post(
                "/v1/decisions/evaluate",
                headers={"Idempotency-Key": "long-running"},
                json=_request_payload(),
            )
        )
        await started.wait()
        await asyncio.sleep(1.2)
        concurrent = await endpoint_client.post(
            "/v1/decisions/evaluate",
            headers={"Idempotency-Key": "long-running"},
            json=_request_payload(),
        )
        finish.set()
        completed = await first

    assert concurrent.status_code == 409
    assert concurrent.json()["detail"]["error"] == "evaluate_idempotency_in_flight"
    assert completed.status_code == 200, completed.text
    assert evaluator.await_count == 1
