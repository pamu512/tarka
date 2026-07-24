"""Vendor marketplace adapters (KYC/KYB/fraud signal providers)."""

from decision_api.vendors.base import (
    BaseVendorPlugin,
    NormalizedVendorSignal,
    VendorAdapter,
    VendorFetchContext,
    VendorTier,
)
from decision_api.vendors.exceptions import (
    VendorAuditConfigurationError,
    VendorTimeoutError,
    VendorUpstreamError,
)
from decision_api.vendors.registry import (
    get_adapter,
    list_registered_vendors,
    register_adapter,
)

__all__ = [
    "BaseVendorPlugin",
    "NormalizedVendorSignal",
    "VendorAdapter",
    "VendorAuditConfigurationError",
    "VendorFetchContext",
    "VendorTier",
    "VendorTimeoutError",
    "VendorUpstreamError",
    "get_adapter",
    "list_registered_vendors",
    "register_adapter",
]
