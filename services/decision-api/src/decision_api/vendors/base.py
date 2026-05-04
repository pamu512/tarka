"""Abstract vendor adapter + unified ontology (0–100 risk scale)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

import httpx


class VendorTier(str, Enum):
    CHEAP = "cheap"
    STANDARD = "standard"
    PREMIUM = "premium"


class NormalizedVendorSignal:
    __slots__ = ("vendor_id", "score_0_100", "reason_codes", "raw_meta")

    def __init__(
        self,
        vendor_id: str,
        score_0_100: float,
        reason_codes: list[str],
        raw_meta: dict[str, Any] | None = None,
    ) -> None:
        self.vendor_id = vendor_id
        self.score_0_100 = max(0.0, min(100.0, float(score_0_100)))
        self.reason_codes = reason_codes
        self.raw_meta = raw_meta or {}


class VendorAdapter(ABC):
    vendor_id: str
    tier: VendorTier = VendorTier.STANDARD

    @abstractmethod
    async def fetch_signal(
        self,
        http: httpx.AsyncClient,
        tenant_id: str,
        entity_id: str,
        features: dict[str, Any],
        *,
        budget_ms: float,
    ) -> NormalizedVendorSignal:
        """Fetch and normalize; must respect ``budget_ms`` (caller enforces dynamic timeout)."""

    def cost_weight(self) -> float:
        return {VendorTier.CHEAP: 1.0, VendorTier.STANDARD: 2.0, VendorTier.PREMIUM: 4.0}[self.tier]
