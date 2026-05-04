"""Register vendor plugins from application settings (opt-in; no fake vendors)."""

from __future__ import annotations

import logging

from decision_api.config import settings
from decision_api.vendors.plugins.ip_api import IpApiVendorCredentials, IpApiVendorPlugin
from decision_api.vendors.registry import register_adapter

log = logging.getLogger("decision-api.vendors")


def install_vendor_plugins_from_settings() -> None:
    """Idempotent-style registration: safe to call on each process start."""
    if settings.vendor_ipapi_enabled:
        creds = IpApiVendorCredentials(
            api_key=(settings.vendor_ipapi_api_key or None),
            base_url=settings.vendor_ipapi_base_url,
        )
        register_adapter("ip_api", IpApiVendorPlugin(creds))
        log.info("Registered vendor plugin: ip_api")
