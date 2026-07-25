"""Compatibility shim for ``tarka_vendor_finops.*`` imports.

Canonical package: ``integration_ingress.vendor_finops``.
Removal gate: delete this package when no callers import ``tarka_vendor_finops``
(rg -n 'tarka_vendor_finops' --glob '*.py').
"""

from integration_ingress.vendor_finops import (  # noqa: F401
    CostRegistry,
    IntegrationRouter,
    PreflightResult,
    SignalKind,
    VendorSignalCache,
    cache_ttl_for_vendor,
)

__all__ = [
    "SignalKind",
    "VendorSignalCache",
    "cache_ttl_for_vendor",
    "CostRegistry",
    "IntegrationRouter",
    "PreflightResult",
]
