"""Register vendor plugins from application settings (opt-in; no fake vendors)."""

from __future__ import annotations

import logging
import os

from decision_api.config import settings
from decision_api.vendors.plugins.fingerprint import (
    FingerprintCredentials,
    FingerprintVendorPlugin,
)
from decision_api.vendors.plugins.incognia import (
    IncogniaCredentials,
    IncogniaVendorPlugin,
)
from decision_api.vendors.plugins.ip_api import (
    IpApiVendorCredentials,
    IpApiVendorPlugin,
)
from decision_api.vendors.plugins.opensanctions import (
    OpenSanctionsCredentials,
    OpenSanctionsVendorPlugin,
)
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

    fp_key = os.environ.get("TARKA_VENDOR_FINGERPRINT_API_KEY", "").strip()
    if fp_key:
        register_adapter(
            "fingerprint",
            FingerprintVendorPlugin(
                FingerprintCredentials(
                    api_key=fp_key,
                    base_url=os.environ.get(
                        "TARKA_VENDOR_FINGERPRINT_BASE_URL", "https://api.fpjs.io"
                    ).strip(),
                )
            ),
        )
        log.info("Registered vendor plugin: fingerprint")

    inc_id = os.environ.get("TARKA_VENDOR_INCOGNIA_CLIENT_ID", "").strip()
    inc_secret = os.environ.get("TARKA_VENDOR_INCOGNIA_CLIENT_SECRET", "").strip()
    if inc_id and inc_secret:
        register_adapter(
            "incognia",
            IncogniaVendorPlugin(
                IncogniaCredentials(
                    client_id=inc_id,
                    client_secret=inc_secret,
                    base_url=os.environ.get(
                        "TARKA_VENDOR_INCOGNIA_BASE_URL", "https://api.incognia.com"
                    ).strip(),
                )
            ),
        )
        log.info("Registered vendor plugin: incognia")

    os_key = os.environ.get("TARKA_VENDOR_OPENSANCTIONS_API_KEY", "").strip()
    if os_key:
        register_adapter(
            "opensanctions",
            OpenSanctionsVendorPlugin(
                OpenSanctionsCredentials(
                    api_key=os_key,
                    base_url=os.environ.get(
                        "TARKA_VENDOR_OPENSANCTIONS_BASE_URL",
                        "https://api.opensanctions.org",
                    ).strip(),
                    dataset=os.environ.get(
                        "TARKA_VENDOR_OPENSANCTIONS_DATASET", "default"
                    ).strip()
                    or "default",
                )
            ),
        )
        log.info("Registered vendor plugin: opensanctions")
