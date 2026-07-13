"""Async OSINT NATS payload carries tenant data residency for integration-ingress guards."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from decision_api.async_osint_redis import publish_async_enrichment_request


@pytest.mark.asyncio
async def test_publish_async_enrichment_request_includes_data_residency_region() -> (
    None
):
    broker = AsyncMock()
    body = MagicMock()
    body.tenant_id = "t1"
    body.entity_id = "e1"
    body.payload = {"ip": "1.1.1.1"}

    await publish_async_enrichment_request(
        broker,
        body,
        "trace-abc",
        tenant_flags={"data_residency_region": "EU"},
    )

    broker.publish.assert_called_once()
    _subject, payload_bytes, *_rest = broker.publish.call_args[0]
    msg = json.loads(payload_bytes.decode("utf-8"))
    assert msg.get("data_residency_region") == "EU"
    assert msg.get("tenant_id") == "t1"
