"""DLQ publish helper (E2)."""

import json
from unittest.mock import AsyncMock

import pytest
from event_ingest.config import settings
from event_ingest.main import (
    _dlq_overlaps_consumer,
    _is_parked_evaluate_envelope,
    _publish_evaluate_dlq,
)


def test_default_dlq_subject_is_outside_consumer_wildcard() -> None:
    assert settings.ingest_dlq_subject == "fraud.dlq.evaluate"
    assert _dlq_overlaps_consumer(settings.ingest_dlq_subject, settings.subject_prefix) is False


def test_legacy_dlq_subject_overlaps_consumer() -> None:
    assert _dlq_overlaps_consumer("fraud.events.dlq", "fraud.events") is True
    assert _dlq_overlaps_consumer("fraud.dlq.evaluate", "fraud.events") is False


def test_parked_evaluate_envelope_is_not_re_evaluated() -> None:
    assert _is_parked_evaluate_envelope({"kind": "evaluate_4xx", "event": {}}) is True
    assert _is_parked_evaluate_envelope({"tenant_id": "t1", "event_type": "login"}) is False


@pytest.mark.asyncio
async def test_publish_evaluate_dlq_envelope(monkeypatch):
    import event_ingest.main as main_mod

    monkeypatch.setattr(main_mod.settings, "ingest_dlq_subject", "fraud.dlq.evaluate")
    js = AsyncMock()
    await _publish_evaluate_dlq(
        js,
        nats_subject="fraud.events.t1.login",
        raw_event={"tenant_id": "t1", "_ingest_id": "x"},
        eval_body={"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
        status_code=422,
        response_text='{"detail":"bad"}',
    )
    js.publish.assert_called_once()
    call_args = js.publish.call_args
    assert call_args[0][0] == "fraud.dlq.evaluate"
    body = json.loads(call_args[0][1].decode())
    assert body["schema_version"] == "1"
    assert body["kind"] == "evaluate_4xx"
    assert body["status_code"] == 422
    assert body["nats_source_subject"] == "fraud.events.t1.login"


@pytest.mark.asyncio
async def test_publish_skips_when_subject_empty(monkeypatch):
    import event_ingest.main as main_mod

    monkeypatch.setattr(main_mod.settings, "ingest_dlq_subject", "")
    js = AsyncMock()
    await _publish_evaluate_dlq(
        js,
        nats_subject="x",
        raw_event={},
        eval_body={},
        status_code=400,
        response_text="",
    )
    js.publish.assert_not_called()


@pytest.mark.asyncio
async def test_park_4xx_acks_only_after_dlq(monkeypatch):
    import event_ingest.main as main_mod
    from event_ingest.main import _park_evaluate_4xx

    monkeypatch.setattr(main_mod.settings, "ingest_dlq_publish_on_evaluate_4xx", True)
    monkeypatch.setattr(main_mod.settings, "ingest_dlq_subject", "fraud.dlq.evaluate")
    monkeypatch.setattr(main_mod.settings, "subject_prefix", "fraud.events")
    js = AsyncMock()
    ok = await _park_evaluate_4xx(
        js,
        nats_subject="fraud.events.t1.login",
        raw_event={"tenant_id": "t1"},
        eval_body={"entity_id": "e1"},
        status_code=422,
        response_text="bad",
    )
    assert ok is True
    js.publish.assert_called_once()


@pytest.mark.asyncio
async def test_park_4xx_nak_when_dlq_subject_inside_consumer_wildcard(monkeypatch):
    import event_ingest.main as main_mod
    from event_ingest.main import _park_evaluate_4xx

    monkeypatch.setattr(main_mod.settings, "ingest_dlq_publish_on_evaluate_4xx", True)
    monkeypatch.setattr(main_mod.settings, "ingest_dlq_subject", "fraud.events.dlq")
    monkeypatch.setattr(main_mod.settings, "subject_prefix", "fraud.events")
    js = AsyncMock()
    ok = await _park_evaluate_4xx(
        js,
        nats_subject="fraud.events.t1.login",
        raw_event={"tenant_id": "t1"},
        eval_body={"entity_id": "e1"},
        status_code=422,
        response_text="bad",
    )
    assert ok is False
    js.publish.assert_not_called()


@pytest.mark.asyncio
async def test_park_4xx_nak_when_dlq_subject_empty(monkeypatch):
    import event_ingest.main as main_mod
    from event_ingest.main import _park_evaluate_4xx

    monkeypatch.setattr(main_mod.settings, "ingest_dlq_publish_on_evaluate_4xx", True)
    monkeypatch.setattr(main_mod.settings, "ingest_dlq_subject", "")
    js = AsyncMock()
    ok = await _park_evaluate_4xx(
        js,
        nats_subject="x",
        raw_event={},
        eval_body={},
        status_code=404,
        response_text="",
    )
    assert ok is False
    js.publish.assert_not_called()


@pytest.mark.asyncio
async def test_park_4xx_nak_when_publish_fails(monkeypatch):
    import event_ingest.main as main_mod
    from event_ingest.main import _park_evaluate_4xx

    monkeypatch.setattr(main_mod.settings, "ingest_dlq_publish_on_evaluate_4xx", True)
    monkeypatch.setattr(main_mod.settings, "ingest_dlq_subject", "fraud.dlq.evaluate")
    monkeypatch.setattr(main_mod.settings, "subject_prefix", "fraud.events")
    js = AsyncMock()
    js.publish = AsyncMock(side_effect=RuntimeError("js down"))
    ok = await _park_evaluate_4xx(
        js,
        nats_subject="x",
        raw_event={},
        eval_body={},
        status_code=422,
        response_text="",
    )
    assert ok is False
