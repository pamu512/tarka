"""Cost-aware vendor invocation: only premium vendors when base score warrants."""

from __future__ import annotations

from typing import Any

import httpx

from decision_api.vendors.base import NormalizedVendorSignal, VendorTier
from decision_api.vendors.registry import get_adapter


async def maybe_invoke_vendor(
    http: httpx.AsyncClient,
    *,
    vendor_id: str,
    tenant_id: str,
    entity_id: str,
    features: dict[str, Any],
    base_rule_score: float,
    budget_ms: float,
) -> NormalizedVendorSignal | None:
    """Skip expensive vendors on low base scores (configurable threshold)."""
    adapter = get_adapter(vendor_id)
    if adapter is None:
        return None
    threshold = 50.0
    if adapter.tier == VendorTier.PREMIUM and base_rule_score < threshold:
        return None
    return await adapter.fetch_signal(
        http, tenant_id, entity_id, features, budget_ms=budget_ms
    )
