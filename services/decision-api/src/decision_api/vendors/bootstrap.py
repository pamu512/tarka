"""Register vendor plugins from application settings (opt-in; no fake vendors)."""

from __future__ import annotations

import logging
import os

from decision_api.config import settings
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
        from decision_api.vendors.plugins.fingerprint import (
            FingerprintCredentials,
            FingerprintVendorPlugin,
        )

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
        from decision_api.vendors.plugins.incognia import (
            IncogniaCredentials,
            IncogniaVendorPlugin,
        )

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

    cb_key = os.environ.get("TARKA_VENDOR_CHARGEBACK_ALERT_API_KEY", "").strip()
    cb_base = os.environ.get("TARKA_VENDOR_CHARGEBACK_ALERT_BASE_URL", "").strip()
    if cb_key and cb_base:
        from decision_api.vendors.plugins.chargeback_alert import (
            ChargebackAlertCredentials,
            ChargebackAlertVendorPlugin,
        )

        register_adapter(
            "chargeback_alert",
            ChargebackAlertVendorPlugin(
                ChargebackAlertCredentials(api_key=cb_key, base_url=cb_base)
            ),
        )
        log.info("Registered vendor plugin: chargeback_alert")

    kyb_key = os.environ.get("TARKA_VENDOR_IDENTITY_KYB_API_KEY", "").strip()
    kyb_base = os.environ.get("TARKA_VENDOR_IDENTITY_KYB_BASE_URL", "").strip()
    if kyb_key and kyb_base:
        from decision_api.vendors.plugins.identity_kyb import (
            IdentityKybCredentials,
            IdentityKybVendorPlugin,
        )

        register_adapter(
            "identity_kyb",
            IdentityKybVendorPlugin(
                IdentityKybCredentials(api_key=kyb_key, base_url=kyb_base)
            ),
        )
        log.info("Registered vendor plugin: identity_kyb")

    brand_key = os.environ.get("TARKA_VENDOR_BRAND_API_KEY", "").strip()
    brand_base = os.environ.get("TARKA_VENDOR_BRAND_BASE_URL", "").strip()
    if brand_key and brand_base:
        from decision_api.vendors.plugins.brand_protection import (
            BrandProtectionCredentials,
            BrandProtectionVendorPlugin,
        )

        register_adapter(
            "brand_protection",
            BrandProtectionVendorPlugin(
                BrandProtectionCredentials(api_key=brand_key, base_url=brand_base)
            ),
        )
        log.info("Registered vendor plugin: brand_protection")

    wa_key = os.environ.get("TARKA_VENDOR_WORKER_AUTH_API_KEY", "").strip()
    wa_base = os.environ.get("TARKA_VENDOR_WORKER_AUTH_BASE_URL", "").strip()
    if wa_key and wa_base:
        from decision_api.vendors.plugins.worker_auth import (
            WorkerAuthCredentials,
            WorkerAuthVendorPlugin,
        )

        register_adapter(
            "worker_auth",
            WorkerAuthVendorPlugin(
                WorkerAuthCredentials(api_key=wa_key, base_url=wa_base)
            ),
        )
        log.info("Registered vendor plugin: worker_auth")

    vis_key = os.environ.get("TARKA_VENDOR_VISION_POD_API_KEY", "").strip()
    vis_base = os.environ.get("TARKA_VENDOR_VISION_POD_BASE_URL", "").strip()
    if vis_key and vis_base:
        from decision_api.vendors.plugins.vision_pod import (
            VisionPodCredentials,
            VisionPodVendorPlugin,
        )

        register_adapter(
            "vision_pod",
            VisionPodVendorPlugin(
                VisionPodCredentials(api_key=vis_key, base_url=vis_base)
            ),
        )
        log.info("Registered vendor plugin: vision_pod")
