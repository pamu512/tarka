"""Wire ``tarka_vendor_finops`` to integration-ingress settings and Postgres audit."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from integration_ingress.config import settings
from integration_ingress.db import SessionLocal
from integration_ingress.models import OsintFinopsAudit

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from tarka_vendor_finops.router import IntegrationRouter


def _ttl_overrides_from_settings() -> dict[str, int]:
    return {
        "shodan": int(settings.osint_ttl_ip_seconds),
        "abuseipdb": int(settings.osint_ttl_ip_seconds),
        "greynoise": int(settings.osint_ttl_ip_seconds),
        "ipinfo": int(settings.osint_ttl_ip_seconds),
        "ip_api": int(settings.osint_ttl_ip_seconds),
        "emailrep": int(settings.osint_ttl_email_seconds),
        "gravatar": int(settings.osint_ttl_email_seconds),
        "hibp": int(settings.osint_ttl_email_seconds),
        "numverify": int(settings.osint_ttl_phone_seconds),
        "rdap": int(settings.osint_ttl_domain_seconds),
        "github": int(settings.osint_ttl_identity_seconds),
    }


async def _audit_sink(record: dict[str, Any]) -> None:
    async with SessionLocal() as session:
        session.add(OsintFinopsAudit(**record))
        await session.commit()


def build_finops_router(redis: Redis | None) -> IntegrationRouter | None:
    """Return a router when FinOps + Redis are enabled; otherwise ``None``."""
    if redis is None or not settings.osint_finops_enabled:
        return None
    from tarka_vendor_finops.router import IntegrationRouter  # noqa: PLC0415

    return IntegrationRouter(
        redis=redis,
        daily_budget_usd=Decimal(str(settings.osint_daily_budget_usd)),
        ttl_overrides=_ttl_overrides_from_settings(),
        audit_sink=_audit_sink,
    )
