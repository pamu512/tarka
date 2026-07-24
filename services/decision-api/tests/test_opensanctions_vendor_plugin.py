"""Callable OpenSanctions plugin + biometrics signal mapping."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from decision_api.vendors.base import VendorFetchContext
from decision_api.vendors.plugins.opensanctions import (
    OpenSanctionsCredentials,
    OpenSanctionsVendorPlugin,
)


def test_opensanctions_no_match_signal() -> None:
    plugin = OpenSanctionsVendorPlugin(
        OpenSanctionsCredentials(api_key="test-key-opensanctions")
    )
    signals = plugin._signals_from_body(
        json.dumps({"responses": {"q1": {"results": []}}}),
        200,
        None,
    )
    assert len(signals) == 1
    assert signals[0].vendor_id == "opensanctions"
    assert signals[0].score_0_100 == 5.0
    assert "opensanctions:no_match" in signals[0].reason_codes


def test_opensanctions_high_match_signal() -> None:
    plugin = OpenSanctionsVendorPlugin(
        OpenSanctionsCredentials(api_key="test-key-opensanctions")
    )
    body = {
        "responses": {
            "q1": {
                "results": [
                    {"id": "NK-1", "caption": "Example Person", "score": 0.92},
                ]
            }
        }
    }
    signals = plugin._signals_from_body(json.dumps(body), 200, None)
    assert signals[0].score_0_100 == 92.0
    assert "opensanctions:high_confidence" in signals[0].reason_codes


@pytest.mark.asyncio
async def test_opensanctions_fetch_signals_http_mock(httpx_mock=None) -> None:
    import httpx

    plugin = OpenSanctionsVendorPlugin(
        OpenSanctionsCredentials(api_key="test-key-opensanctions")
    )
    plugin._persist_integration_audit = AsyncMock()  # type: ignore[method-assign]

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"responses": {"q1": {"results": []}}},
        )
    )
    async with httpx.AsyncClient(transport=transport) as http:
        ctx = VendorFetchContext(
            http=http,
            session=None,
            trace_id=uuid.uuid4(),
            tenant_id="t1",
            entity_id="e1",
            features={"entity_name": "Jane Doe"},
            budget_ms=5000.0,
        )
        signals = await plugin.fetch_signals(ctx)
    assert signals[0].reason_codes == ["opensanctions:no_match"]
