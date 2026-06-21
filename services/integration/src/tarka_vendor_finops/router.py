"""Pre-flight: cache → daily budget → short-circuit; audit estimated savings to Postgres."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from redis.asyncio import Redis

from tarka_vendor_finops.cache import VendorSignalCache, cache_ttl_for_vendor

log = logging.getLogger(__name__)


class CostRegistry:
    """Estimated commercial price per successful vendor HTTP call (USD, for FinOps guardrails)."""

    PRICE_PER_CALL_USD: dict[str, Decimal] = {
        "shodan": Decimal("0.000"),
        "abuseipdb": Decimal("0.001"),
        "greynoise": Decimal("0.002"),
        "ipinfo": Decimal("0.0002"),
        "ip_api": Decimal("0.000"),
        "emailrep": Decimal("0.001"),
        "gravatar": Decimal("0.000"),
        "hibp": Decimal("0.0005"),
        "numverify": Decimal("0.004"),
        "rdap": Decimal("0.000"),
        "github": Decimal("0.000"),
    }

    @classmethod
    def price_usd(cls, vendor_key: str) -> Decimal:
        return cls.PRICE_PER_CALL_USD.get(vendor_key, Decimal("0.0001"))


@dataclass
class PreflightResult:
    short_circuit: bool
    """If True, skip the outbound HTTP call."""
    cached_json: dict[str, Any] | None
    """Positive-cache payload to treat like HTTP 200 JSON; None for negative cache or budget block."""
    skip_reason: str | None
    estimated_savings_usd: Decimal


class _BudgetStore(Protocol):
    async def spent_today_usd(self, tenant_id: str) -> Decimal: ...
    async def add_spend_usd(self, tenant_id: str, amount: Decimal) -> Decimal: ...


class RedisDailyBudgetStore:
    """Rolling daily spend per tenant (UTC date) in USD as a Redis float."""

    def __init__(self, redis: Redis, *, key_prefix: str = "osint:budget") -> None:
        self._r = redis
        self._prefix = key_prefix

    def _key(self, tenant_id: str) -> str:
        d = datetime.now(UTC).strftime("%Y-%m-%d")
        tid = (tenant_id or "global").strip() or "global"
        return f"{self._prefix}:{tid}:{d}"

    async def spent_today_usd(self, tenant_id: str) -> Decimal:
        raw = await self._r.get(self._key(tenant_id))
        if not raw:
            return Decimal("0")
        try:
            return Decimal(str(float(raw)))
        except (TypeError, ValueError):
            return Decimal("0")

    async def add_spend_usd(self, tenant_id: str, amount: Decimal) -> Decimal:
        if amount <= 0:
            return await self.spent_today_usd(tenant_id)
        k = self._key(tenant_id)
        async with self._r.pipeline(transaction=True) as pipe:
            await pipe.incrbyfloat(k, float(amount))
            await pipe.expire(k, 90_000)
            res = await pipe.execute()
        return Decimal(str(res[0]))


AuditSink = Callable[[dict[str, Any]], Awaitable[None]]


class IntegrationRouter:
    """Pre-flight checks before OSINT vendor HTTP: cache hit, negative cache, daily budget."""

    def __init__(
        self,
        *,
        redis: Redis,
        daily_budget_usd: Decimal,
        ttl_overrides: dict[str, int] | None = None,
        budget_store: _BudgetStore | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self._redis = redis
        self._cache = VendorSignalCache(redis)
        self._daily_budget = daily_budget_usd
        self._ttl_overrides = ttl_overrides
        self._budget = budget_store or RedisDailyBudgetStore(redis)
        self._audit_sink = audit_sink

    async def _audit_skip(
        self,
        *,
        tenant_id: str | None,
        vendor_key: str,
        skip_reason: str,
        estimated_savings_usd: Decimal,
        detail: dict[str, Any] | None = None,
    ) -> None:
        if self._audit_sink is None:
            return
        try:
            await self._audit_sink(
                {
                    "tenant_id": (tenant_id or "global").strip() or "global",
                    "vendor_key": vendor_key,
                    "skip_reason": skip_reason,
                    "estimated_savings_usd": float(estimated_savings_usd),
                    "detail_json": detail or {},
                }
            )
        except Exception as e:
            log.warning("osint finops audit insert failed: %s", e)
        else:
            log.info(
                "EstimatedSavings=%.6f USD tenant=%s vendor=%s skip_reason=%s",
                float(estimated_savings_usd),
                (tenant_id or "global").strip() or "global",
                vendor_key,
                skip_reason,
            )

    async def preflight_http_get(
        self,
        *,
        tenant_id: str | None,
        vendor_key: str,
        url: str,
    ) -> PreflightResult:
        tid = (tenant_id or "global").strip() or "global"
        price = CostRegistry.price_usd(vendor_key)
        cache_ttl_for_vendor(vendor_key, ttl_overrides=self._ttl_overrides)

        entry = await self._cache.get_json(tid, vendor_key, url)
        if entry is not None:
            neg, payload = VendorSignalCache.unwrap_entry(entry)
            if neg:
                await self._audit_skip(
                    tenant_id=tid,
                    vendor_key=vendor_key,
                    skip_reason="negative_cache_hit",
                    estimated_savings_usd=price,
                    detail={"url": url[:512]},
                )
                return PreflightResult(
                    short_circuit=True,
                    cached_json=None,
                    skip_reason="negative_cache_hit",
                    estimated_savings_usd=price,
                )
            if payload is not None:
                await self._audit_skip(
                    tenant_id=tid,
                    vendor_key=vendor_key,
                    skip_reason="cache_hit",
                    estimated_savings_usd=price,
                    detail={"url": url[:512]},
                )
                return PreflightResult(
                    short_circuit=True,
                    cached_json=payload,
                    skip_reason="cache_hit",
                    estimated_savings_usd=price,
                )

        spent = await self._budget.spent_today_usd(tid)
        if price > 0 and spent + price > self._daily_budget:
            await self._audit_skip(
                tenant_id=tid,
                vendor_key=vendor_key,
                skip_reason="daily_budget_exceeded",
                estimated_savings_usd=price,
                detail={
                    "spent_usd": float(spent),
                    "limit_usd": float(self._daily_budget),
                    "url": url[:256],
                },
            )
            return PreflightResult(
                short_circuit=True,
                cached_json=None,
                skip_reason="daily_budget_exceeded",
                estimated_savings_usd=price,
            )

        return PreflightResult(
            short_circuit=False,
            cached_json=None,
            skip_reason=None,
            estimated_savings_usd=Decimal("0"),
        )

    async def record_successful_call(
        self,
        *,
        tenant_id: str | None,
        vendor_key: str,
        url: str,
        payload: dict[str, Any],
    ) -> None:
        tid = (tenant_id or "global").strip() or "global"
        price = CostRegistry.price_usd(vendor_key)
        ttl = cache_ttl_for_vendor(vendor_key, ttl_overrides=self._ttl_overrides)
        await self._cache.set_positive(tid, vendor_key, url, payload, ttl_seconds=ttl)
        if price > 0:
            await self._budget.add_spend_usd(tid, price)

    async def record_negative_outcome(
        self,
        *,
        tenant_id: str | None,
        vendor_key: str,
        url: str,
        status_code: int | None,
        error_class: str,
        message: str,
    ) -> None:
        tid = (tenant_id or "global").strip() or "global"
        ttl = cache_ttl_for_vendor(vendor_key, ttl_overrides=self._ttl_overrides)
        await self._cache.set_negative(
            tid,
            vendor_key,
            url,
            status_code=status_code,
            error_class=error_class,
            message=message,
            ttl_seconds=ttl,
        )
