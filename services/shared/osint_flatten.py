"""Flatten OSINT / light enrichment API payloads into decision feature dicts.

Used by feature-service (HTTP path), decision-api (Redis async path), and tests.
"""

from __future__ import annotations

from typing import Any


def normalize_location_aliases(features: dict[str, Any]) -> None:
    """Alias OSINT IP geo into generic ip_geo_* keys for downstream rule engines."""
    if features.get("osint_ip_geo_lat") is not None and features.get("ip_geo_lat") is None:
        features["ip_geo_lat"] = features["osint_ip_geo_lat"]
    if features.get("osint_ip_geo_lon") is not None and features.get("ip_geo_lon") is None:
        features["ip_geo_lon"] = features["osint_ip_geo_lon"]
    if features.get("osint_ip_geo_timezone") and not features.get("ip_geo_timezone"):
        features["ip_geo_timezone"] = features["osint_ip_geo_timezone"]


def flatten_light_enrichment_response(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten integration-ingress /v1/enrich style JSON into numeric/boolean features."""
    features: dict[str, Any] = {}
    enrichments = data.get("enrichments", {})
    if not isinstance(enrichments, dict):
        enrichments = {}

    email_data = enrichments.get("email", {})
    if email_data:
        features["email_risk_score"] = email_data.get("risk_score", 0)
        features["is_disposable_email"] = email_data.get("is_disposable", False)
        features["is_free_provider"] = email_data.get("is_free_provider", False)
        features["gravatar_exists"] = email_data.get("gravatar_exists", False)
        features["email_domain"] = email_data.get("domain", "")

    phone_data = enrichments.get("phone", {})
    if phone_data:
        features["phone_risk_score"] = phone_data.get("risk_score", 0)
        features["is_voip_phone"] = phone_data.get("is_voip_likely", False)
        features["phone_country_code"] = phone_data.get("country_code")

    ip_data = enrichments.get("ip", {})
    if ip_data:
        features["ip_risk_score"] = ip_data.get("risk_score", 0)
        features["is_proxy_ip"] = ip_data.get("is_proxy", False)
        features["is_hosting_ip"] = ip_data.get("is_hosting", False)
        features["ip_country"] = ip_data.get("country")

    features["aggregate_risk_score"] = data.get("aggregate_risk_score", 0)
    return features


def flatten_osint_response(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten integration-ingress /v1/osint style JSON into feature keys."""
    features: dict[str, Any] = {}
    if not isinstance(data, dict):
        return features

    features["osint_composite_risk"] = data.get("composite_risk_score", 0)
    features["osint_risk_level"] = data.get("risk_level", "unknown")

    enrichments = data.get("enrichments", {})
    if not isinstance(enrichments, dict):
        enrichments = {}

    ip_data = enrichments.get("ip", {})
    ip_flags = ip_data.get("flags", {}) if isinstance(ip_data, dict) else {}
    features["osint_ip_vpn"] = ip_flags.get("vpn", False)
    features["osint_ip_proxy"] = ip_flags.get("proxy", False)
    features["osint_ip_tor"] = ip_flags.get("tor", False)
    features["osint_ip_hosting"] = ip_flags.get("hosting", False)
    vulns = ip_data.get("vulnerabilities", []) if isinstance(ip_data, dict) else []
    features["osint_ip_vuln_count"] = len(vulns) if isinstance(vulns, list) else 0
    geo_block = ip_data.get("geo") if isinstance(ip_data, dict) else {}
    if isinstance(geo_block, dict):
        la = geo_block.get("lat")
        lo = geo_block.get("lon")
        try:
            if la is not None:
                features["osint_ip_geo_lat"] = float(la)
            if lo is not None:
                features["osint_ip_geo_lon"] = float(lo)
        except (TypeError, ValueError):
            pass
        tzg = geo_block.get("timezone")
        if isinstance(tzg, str) and tzg:
            features["osint_ip_geo_timezone"] = tzg

    email_data = enrichments.get("email", {})
    if isinstance(email_data, dict):
        features["osint_email_disposable"] = email_data.get("is_disposable", False)
        features["osint_email_breach_count"] = email_data.get("breach_count", 0)
        features["osint_email_reputation"] = email_data.get("reputation", 0)

    phone_data = enrichments.get("phone", {})
    if isinstance(phone_data, dict):
        features["osint_phone_voip"] = phone_data.get("is_voip", False)

    normalize_location_aliases(features)
    return features
