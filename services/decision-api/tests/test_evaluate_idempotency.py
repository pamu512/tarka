from __future__ import annotations

import asyncio

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
