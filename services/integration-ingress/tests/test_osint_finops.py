"""FinOps pre-flight: cache hit and daily budget short-circuit."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from tarka_vendor_finops.router import IntegrationRouter


@pytest.mark.asyncio
async def test_preflight_positive_cache_short_circuits() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(
        return_value='{"__meta__":{"negative":false},"payload":{"hello":"world"}}'
    )
    r = IntegrationRouter(redis=redis, daily_budget_usd=Decimal("100"), audit_sink=None)
    pf = await r.preflight_http_get(
        tenant_id="acme", vendor_key="shodan", url="https://internetdb.shodan.io/1.1.1.1"
    )
    assert pf.short_circuit
    assert pf.skip_reason == "cache_hit"
    assert pf.cached_json == {"hello": "world"}
    assert pf.estimated_savings_usd >= 0


@pytest.mark.asyncio
async def test_preflight_negative_cache_short_circuits() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(
        return_value='{"__meta__":{"negative":true,"status_code":404,"error_class":"HTTPNotFound","message":"nope"},"payload":null}'
    )
    r = IntegrationRouter(redis=redis, daily_budget_usd=Decimal("100"), audit_sink=None)
    pf = await r.preflight_http_get(
        tenant_id="acme", vendor_key="emailrep", url="https://emailrep.io/a@b.co"
    )
    assert pf.short_circuit
    assert pf.skip_reason == "negative_cache_hit"
    assert pf.cached_json is None


@pytest.mark.asyncio
async def test_preflight_budget_blocks_when_spend_high() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    class _Budget:
        async def spent_today_usd(self, tenant_id: str) -> Decimal:
            return Decimal("1000")

        async def add_spend_usd(self, tenant_id: str, amount: Decimal) -> Decimal:
            return Decimal("1000") + amount

    r = IntegrationRouter(
        redis=redis,
        daily_budget_usd=Decimal("1000.0"),
        budget_store=_Budget(),
        audit_sink=None,
    )
    pf = await r.preflight_http_get(
        tenant_id="acme", vendor_key="abuseipdb", url="https://api.abuseipdb.com/x"
    )
    assert pf.short_circuit
    assert pf.skip_reason == "daily_budget_exceeded"


@pytest.mark.asyncio
async def test_preflight_audit_sink_receives_estimated_savings() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    audit = AsyncMock()

    class _Budget:
        async def spent_today_usd(self, tenant_id: str) -> Decimal:
            return Decimal("0")

        async def add_spend_usd(self, tenant_id: str, amount: Decimal) -> Decimal:
            return amount

    r = IntegrationRouter(
        redis=redis,
        daily_budget_usd=Decimal("100"),
        budget_store=_Budget(),
        audit_sink=audit,
    )
    await r._audit_skip(
        tenant_id="t1",
        vendor_key="shodan",
        skip_reason="cache_hit",
        estimated_savings_usd=Decimal("0.000"),
        detail={"url": "https://example/x"},
    )
    audit.assert_awaited_once()
    rec = audit.await_args.args[0]
    assert rec["tenant_id"] == "t1"
    assert rec["vendor_key"] == "shodan"
    assert rec["skip_reason"] == "cache_hit"
    assert rec["estimated_savings_usd"] == 0.0
    assert "url" in rec["detail_json"]
