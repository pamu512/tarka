"""DLQ publish helper (E2)."""

import json
from unittest.mock import AsyncMock

import pytest

from event_ingest.main import _publish_evaluate_dlq


@pytest.mark.asyncio
async def test_publish_evaluate_dlq_envelope(monkeypatch):
    import event_ingest.main as main_mod

    monkeypatch.setattr(main_mod.settings, "ingest_dlq_subject", "fraud.events.dlq")
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
    assert call_args[0][0] == "fraud.events.dlq"
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
