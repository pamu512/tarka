r"""OSINT FinOps **Integration Router** (stable import path).

Implementation: ``tarka_vendor_finops.router.IntegrationRouter``.

**Pre-flight (before each vendor HTTP GET)** — order is fixed:

1. **Redis ``VendorSignalCache``** — if a fresh entry exists (positive JSON or **negative cache** for 4xx/5xx/429/transport errors), **short-circuit** the network call.
2. **Daily budget** (per tenant, UTC day, Redis counter + ``CostRegistry`` price-per-call) — if the next call would exceed the cap, **short-circuit**.

**Negative caching** — failed or empty vendor responses are stored with the same TTL class as successes so repeat traffic does not hammer dying endpoints.

**Audit plane** — every skip writes **Postgres** ``osint_finops_audit`` with ``estimated_savings_usd`` (avoided vendor price for that call) and ``skip_reason`` (``cache_hit`` \| ``negative_cache_hit`` \| ``daily_budget_exceeded``). Structured logs also emit **EstimatedSavings**.

TTL defaults: IP-class vendors **24h**, email-class **7d** (overridable per vendor via integration-ingress settings → ``finops_setup._ttl_overrides_from_settings``).
"""

from tarka_vendor_finops.router import (
    AuditSink,
    CostRegistry,
    IntegrationRouter,
    PreflightResult,
    RedisDailyBudgetStore,
)

__all__ = [
    "AuditSink",
    "CostRegistry",
    "IntegrationRouter",
    "PreflightResult",
    "RedisDailyBudgetStore",
]
