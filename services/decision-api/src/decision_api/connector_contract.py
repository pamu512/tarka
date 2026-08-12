"""Production connector contract — posture machine for vendor families.

Fail-closed: missing credentials never claim LIVE. Category leaders and
consortium feeds are connectors; Tarka owns packs/bridges/graph.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable


@dataclass(frozen=True)
class ConnectorFamily:
    family_id: str
    display_name: str
    strategy: str  # "connector" | "build" | "hybrid"
    env_credential_keys: tuple[str, ...]
    evidence_tags: tuple[str, ...]
    category_note: str


FAMILIES: dict[str, ConnectorFamily] = {
    "device": ConnectorFamily(
        family_id="device",
        display_name="Device integrity",
        strategy="connector",
        env_credential_keys=(
            "TARKA_VENDOR_FINGERPRINT_API_KEY",
            "TARKA_VENDOR_INCOGNIA_CLIENT_ID",
            "TARKA_VENDOR_INCOGNIA_CLIENT_SECRET",
        ),
        evidence_tags=("vendor:fingerprint", "vendor:incognia", "risk:device"),
        category_note="Incognia / Fingerprint / SHIELD — do not DIY device graph",
    ),
    "sanctions": ConnectorFamily(
        family_id="sanctions",
        display_name="Sanctions / PEP",
        strategy="hybrid",
        env_credential_keys=("TARKA_VENDOR_OPENSANCTIONS_API_KEY",),
        evidence_tags=("vendor:opensanctions", "risk:sanctions"),
        category_note="OpenSanctions/yente Match + continuous ops schedule",
    ),
    "identity_kyb": ConnectorFamily(
        family_id="identity_kyb",
        display_name="Identity KYB / KYC",
        strategy="connector",
        env_credential_keys=(
            "TARKA_VENDOR_IDENTITY_KYB_API_KEY",
            "TARKA_VENDOR_IDENTITY_KYB_BASE_URL",
        ),
        evidence_tags=("vendor:identity_kyb", "risk:kyb"),
        category_note="Sumsub/Persona/Onfido-class — INFORM/DSA verify via vendor",
    ),
    "chargeback_alert": ConnectorFamily(
        family_id="chargeback_alert",
        display_name="Chargeback early alert",
        strategy="connector",
        env_credential_keys=(
            "TARKA_VENDOR_CHARGEBACK_ALERT_API_KEY",
            "TARKA_VENDOR_CHARGEBACK_ALERT_BASE_URL",
        ),
        evidence_tags=("vendor:chargeback_alert", "risk:friendly_fraud"),
        category_note="Ethoca/Verifi-class consortium — do not DIY card-network graph",
    ),
    "worker_auth": ConnectorFamily(
        family_id="worker_auth",
        display_name="Worker face / RTW",
        strategy="connector",
        env_credential_keys=(
            "TARKA_VENDOR_WORKER_AUTH_API_KEY",
            "TARKA_VENDOR_WORKER_AUTH_BASE_URL",
        ),
        evidence_tags=("vendor:worker_auth", "risk:account_rental"),
        category_note="iProov/Onfido-class continuous auth — connector only",
    ),
    "brand_protection": ConnectorFamily(
        family_id="brand_protection",
        display_name="Brand / counterfeit",
        strategy="connector",
        env_credential_keys=(
            "TARKA_VENDOR_BRAND_API_KEY",
            "TARKA_VENDOR_BRAND_BASE_URL",
        ),
        evidence_tags=("vendor:brand", "risk:counterfeit"),
        category_note="Commercial brand-protection API — no DIY crawl",
    ),
}


def _env_present(key: str) -> bool:
    return bool(os.environ.get(key, "").strip())


def posture_for_family(
    family_id: str,
    *,
    registered_vendors: list[str] | None = None,
    last_success_at: str | None = None,
    extra_blockers: list[str] | None = None,
) -> dict[str, Any]:
    fam = FAMILIES.get(family_id)
    if fam is None:
        return {
            "family_id": family_id,
            "status": "unknown_family",
            "live_claim_allowed": False,
            "blockers": ["unknown_family"],
        }
    registered = {str(v).strip().lower() for v in (registered_vendors or []) if v}
    creds_present = [_env_present(k) for k in fam.env_credential_keys]
    # Device family: Fingerprint OR (Incognia id+secret)
    if family_id == "device":
        fp_ok = _env_present("TARKA_VENDOR_FINGERPRINT_API_KEY")
        inc_ok = _env_present("TARKA_VENDOR_INCOGNIA_CLIENT_ID") and _env_present(
            "TARKA_VENDOR_INCOGNIA_CLIENT_SECRET"
        )
        any_creds = fp_ok or inc_ok
        plugin_ok = bool(registered & {"fingerprint", "incognia"})
    else:
        # All declared env keys required (api key + base URL for gateway connectors)
        required = list(fam.env_credential_keys)
        any_creds = all(_env_present(k) for k in required) if required else False
        # Map family → expected vendor_id
        vendor_map = {
            "sanctions": {"opensanctions"},
            "identity_kyb": {"identity_kyb"},
            "chargeback_alert": {"chargeback_alert"},
            "worker_auth": {"worker_auth"},
            "brand_protection": {"brand_protection"},
        }
        plugin_ok = bool(registered & vendor_map.get(family_id, set()))

    blockers: list[str] = []
    if not any_creds:
        blockers.append("credentials_missing")
    if any_creds and not plugin_ok:
        blockers.append("plugin_not_registered")
    if extra_blockers:
        blockers.extend(extra_blockers)

    live = len(blockers) == 0 and any_creds and plugin_ok
    status = "live_ready" if live else ("partial" if any_creds else "unavailable")
    return {
        "family_id": fam.family_id,
        "display_name": fam.display_name,
        "strategy": fam.strategy,
        "status": status,
        "live_claim_allowed": live,
        "last_success_at": last_success_at,
        "blockers": blockers,
        "evidence_tags": list(fam.evidence_tags),
        "env_credential_keys": list(fam.env_credential_keys),
        "category_note": fam.category_note,
        "credentials_present": any(creds_present)
        if family_id == "device"
        else any_creds,
        "plugin_registered": plugin_ok,
        "schema_id": "tarka.connector_posture/v1",
        "observed_at": datetime.now(UTC).isoformat(),
    }


def load_all_connector_posture(
    *,
    registered_vendors: list[str] | None = None,
    last_success_lookup: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    vendors = registered_vendors
    if vendors is None:
        try:
            from decision_api.vendors.registry import list_registered_vendors

            vendors = list_registered_vendors()
        except Exception:
            vendors = []
    families_out: dict[str, Any] = {}
    for fid in FAMILIES:
        last = last_success_lookup(fid) if last_success_lookup else None
        families_out[fid] = posture_for_family(
            fid, registered_vendors=vendors, last_success_at=last
        )
    live_count = sum(1 for p in families_out.values() if p.get("live_claim_allowed"))
    return {
        "schema_id": "tarka.connector_ops_posture/v1",
        "families": families_out,
        "live_ready_count": live_count,
        "family_count": len(families_out),
        "honesty": (
            "live_claim_allowed requires real credentials + registered plugin. "
            "Never forge LIVE partner pins."
        ),
        "contract": {
            "required_fields": [
                "live_claim_allowed",
                "last_success_at",
                "blockers",
                "status",
            ],
            "fail_closed": True,
            "timeout_circuit_audit": "BaseVendorPlugin (retries + Postgres audit)",
        },
    }
