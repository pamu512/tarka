"""Data residency: EU tenants must not open sockets to US-classified OSINT vendors (pre-flight)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from tarka_core.data_residency import DataResidencyViolationError
from tarka_core.tenant_config import DataResidencyRegion, TenantConfig

from integration_ingress.osint import _osint_residency_ctx, _safe_get


@pytest.mark.asyncio
async def test_safe_get_blocks_shodan_before_http_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    record_mock = AsyncMock()
    monkeypatch.setattr(
        "integration_ingress.compliance_residency.record_residency_compliance_block",
        record_mock,
    )

    def _boom(request: httpx.Request) -> httpx.Response:  # pragma: no cover — must not run
        raise AssertionError("HTTP transport must not run for residency-blocked OSINT")

    transport = httpx.MockTransport(_boom)
    tok = _osint_residency_ctx.set(
        ("tenant-eu-osint", TenantConfig(data_residency_region=DataResidencyRegion.EU)),
    )
    try:
        async with httpx.AsyncClient(transport=transport) as http:
            with pytest.raises(DataResidencyViolationError):
                await _safe_get(http, "https://internetdb.shodan.io/8.8.8.8", vendor_key="shodan")
        record_mock.assert_awaited_once()
        kw = record_mock.await_args.kwargs
        assert kw.get("vendor_key") == "shodan"
        assert kw.get("tenant_id") == "tenant-eu-osint"
        assert kw.get("component") == "osint"
    finally:
        _osint_residency_ctx.reset(tok)
