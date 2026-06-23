"""Vendor adapter registry; production registers real HTTP-backed adapters (no built-in stubs)."""

from __future__ import annotations

from decision_api.vendors.base import VendorAdapter

_REGISTRY: dict[str, VendorAdapter] = {}


def register_adapter(vendor_id: str, adapter: VendorAdapter) -> None:
    """Register or replace a vendor adapter (e.g. at application startup from config)."""
    _REGISTRY[vendor_id] = adapter


def list_registered_vendors() -> list[str]:
    return sorted(_REGISTRY.keys())


def get_adapter(vendor_id: str) -> VendorAdapter | None:
    return _REGISTRY.get(vendor_id)
