"""Register built-in vendor stubs; production adds real HTTP clients + secrets."""

from __future__ import annotations

from typing import Any

import httpx

from decision_api.vendors.base import NormalizedVendorSignal, VendorAdapter, VendorTier


class _EchoVendor(VendorAdapter):
    vendor_id = "echo_stub"

    def __init__(self) -> None:
        self.tier = VendorTier.CHEAP

    async def fetch_signal(
        self,
        _http: httpx.AsyncClient,
        tenant_id: str,
        entity_id: str,
        features: dict[str, Any],
        *,
        budget_ms: float,
    ) -> NormalizedVendorSignal:
        _ = budget_ms
        base = float(hash((tenant_id, entity_id)) % 37)
        return NormalizedVendorSignal(
            self.vendor_id,
            score_0_100=base,
            reason_codes=["stub:echo"],
            raw_meta={"features_keys": list(features.keys())[:20]},
        )


_REGISTRY: dict[str, VendorAdapter] = {
    "echo_stub": _EchoVendor(),
}


def list_registered_vendors() -> list[str]:
    return sorted(_REGISTRY.keys())


def get_adapter(vendor_id: str) -> VendorAdapter | None:
    return _REGISTRY.get(vendor_id)
