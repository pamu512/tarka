"""Vendor plugin architecture: ip-api reference, audit persistence, timeout errors."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import ValidationError

from decision_api.models import VendorIntegrationAudit
from decision_api.vendors.exceptions import VendorTimeoutError, VendorUpstreamError
from decision_api.vendors.plugins.ip_api import (
    IpApiVendorCredentials,
    IpApiVendorPlugin,
)


def _success_json() -> str:
    return (
        '{"status":"success","country":"US","countryCode":"US","region":"CA","city":"SF",'
        '"lat":37,"lon":-122,"isp":"TestISP","org":"TestOrg","as":"AS0","proxy":false,'
        '"hosting":false,"mobile":false,"query":"8.8.8.8"}'
    )


@pytest.mark.asyncio
async def test_ip_api_plugin_persists_audit_then_returns_signal() -> None:
    plugin = IpApiVendorPlugin(IpApiVendorCredentials())

    def handler(request: httpx.Request) -> httpx.Response:
        assert "8.8.8.8" in str(request.url)
        return httpx.Response(200, text=_success_json())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        tid = uuid.uuid4()
        sig = await plugin.fetch_signal(
            http,
            "tenant-a",
            "entity-b",
            {"ip": "8.8.8.8"},
            budget_ms=2000.0,
            audit_session=session,
            trace_id=tid,
        )
    assert sig.vendor_id == "ip_api"
    assert 0 <= sig.score_0_100 <= 100
    session.add.assert_called_once()
    row = session.add.call_args[0][0]
    assert isinstance(row, VendorIntegrationAudit)
    assert row.outcome == "success"
    assert row.vendor_id == "ip_api"
    assert row.trace_id == tid
    assert "US" in row.raw_response


@pytest.mark.asyncio
async def test_ip_api_plugin_timeout_records_audit_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = IpApiVendorPlugin(IpApiVendorCredentials())

    async def slow_http(*_a: object, **_kw: object) -> httpx.Response:
        await asyncio.sleep(1.0)
        return httpx.Response(200, text=_success_json())

    monkeypatch.setattr(plugin, "_resilient_get", slow_http)

    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as http:
        session = MagicMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        with pytest.raises(VendorTimeoutError) as ei:
            await plugin.fetch_signal(
                http,
                "tenant-a",
                "entity-b",
                {"ip": "8.8.8.8"},
                budget_ms=80.0,
                audit_session=session,
                trace_id=uuid.uuid4(),
            )
    assert ei.value.reason_code == "VENDOR_TIMEOUT"
    session.add.assert_called_once()
    row = session.add.call_args[0][0]
    assert row.outcome == "timeout"


def test_ip_api_parse_rejects_upstream_status() -> None:
    plugin = IpApiVendorPlugin(IpApiVendorCredentials())
    with pytest.raises(VendorUpstreamError):
        plugin._parse_vendor_payload(
            response_text='{"status":"fail","message":"invalid query"}',
            http_status=200,
            trace_id=uuid.uuid4(),
        )


def test_ip_api_url_requires_valid_ip() -> None:
    plugin = IpApiVendorPlugin(IpApiVendorCredentials())
    with pytest.raises(ValidationError):
        plugin._build_get_url({"ip": "not-an-ip"})
