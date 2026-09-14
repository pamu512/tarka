"""D1c: terminal consumer failures must park on the DLQ, not NAK forever."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from event_ingest.config import settings
from event_ingest.main import _handle_message_failure


def _msg(num_delivered: int) -> SimpleNamespace:
    return SimpleNamespace(
        nak=AsyncMock(),
        ack=AsyncMock(),
        subject="fraud.events.tenant1",
        data=json.dumps({"entity_id": "e1"}).encode(),
        metadata=SimpleNamespace(num_delivered=num_delivered),
    )


def _js() -> SimpleNamespace:
    return SimpleNamespace(publish=AsyncMock())


@pytest.mark.asyncio
async def test_delivery_below_cap_naks_and_keeps_redelivering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ingest_max_deliver", 5)
    msg, js = _msg(2), _js()
    await _handle_message_failure(js, msg, kind="side_effect_failure", eval_body={}, raw_event={})
    msg.nak.assert_awaited_once()
    msg.ack.assert_not_awaited()
    js.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_delivery_parks_on_dlq_and_acks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ingest_max_deliver", 5)
    monkeypatch.setattr(settings, "ingest_dlq_publish_on_side_effect_failure", True)
    monkeypatch.setattr(settings, "ingest_dlq_subject", "fraud.dlq.evaluate")
    msg, js = _msg(5), _js()
    await _handle_message_failure(
        js,
        msg,
        kind="side_effect_failure",
        eval_body={"entity_id": "e1"},
        raw_event={"entity_id": "e1"},
    )
    msg.ack.assert_awaited_once()
    msg.nak.assert_not_awaited()
    subj, payload = js.publish.await_args.args
    assert subj == "fraud.dlq.evaluate"
    envelope = json.loads(payload.decode())
    assert envelope["kind"] == "side_effect_failure"
    assert envelope["event"] == {"entity_id": "e1"}
    assert envelope["deliveries"] == 5


@pytest.mark.asyncio
async def test_terminal_dlq_publish_failure_falls_back_to_nak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ingest_max_deliver", 5)
    monkeypatch.setattr(settings, "ingest_dlq_publish_on_side_effect_failure", True)
    msg, js = _msg(5), _js()
    js.publish = AsyncMock(side_effect=RuntimeError("nats down"))
    await _handle_message_failure(js, msg, kind="evaluate_5xx", eval_body={}, raw_event={})
    msg.nak.assert_awaited_once()
    msg.ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_park_disabled_keeps_naking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ingest_max_deliver", 5)
    monkeypatch.setattr(settings, "ingest_dlq_publish_on_side_effect_failure", False)
    msg, js = _msg(99), _js()
    await _handle_message_failure(js, msg, kind="consumer_error", eval_body={}, raw_event={})
    msg.nak.assert_awaited_once()
    msg.ack.assert_not_awaited()
    js.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_dlq_subject_inside_consumer_wildcard_keeps_naking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2 invariant: a DLQ publish matching {prefix}.> would re-consume itself."""
    monkeypatch.setattr(settings, "ingest_max_deliver", 5)
    monkeypatch.setattr(settings, "ingest_dlq_publish_on_side_effect_failure", True)
    monkeypatch.setattr(settings, "ingest_dlq_subject", "fraud.events.dlq")
    monkeypatch.setattr(settings, "subject_prefix", "fraud.events")
    msg, js = _msg(5), _js()
    await _handle_message_failure(js, msg, kind="side_effect_failure", eval_body={}, raw_event={})
    msg.nak.assert_awaited_once()
    msg.ack.assert_not_awaited()
    js.publish.assert_not_awaited()
