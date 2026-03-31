"""ML score explainability — provides human-readable reason codes for scores."""
from typing import Any

_SIGNAL_EXPLANATIONS = {
    "is_emulator": ("EMULATOR_DETECTED", "Device is running on an emulator"),
    "is_vpn": ("VPN_DETECTED", "VPN or proxy connection detected"),
    "is_bot": ("BOT_DETECTED", "Automated bot behavior detected"),
    "is_repackaged": ("REPACKAGED_APP", "Application has been repackaged/tampered"),
    "is_spoofed_location": ("SPOOFED_LOCATION", "GPS location appears spoofed"),
    "webdriver_detected": ("WEBDRIVER", "Browser automation (WebDriver) detected"),
    "ip_is_datacenter": ("DATACENTER_IP", "IP belongs to a datacenter/hosting provider"),
    "ip_is_proxy": ("PROXY_IP", "IP is a known proxy"),
}


def explain_score(
    score: float,
    features: dict[str, Any],
    model_type: str = "heuristic",
    adaptive_contributions: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """Generate reason codes explaining why a score was assigned.

    Returns a list of { code, description, impact, feature?, value? } dicts.
    """
    reasons: list[dict[str, Any]] = []

    amount = features.get("amount") or features.get("original_amount")
    if amount is not None:
        try:
            amt = float(amount)
            if amt > 5000:
                reasons.append({
                    "code": "HIGH_AMOUNT",
                    "description": f"Transaction amount ${amt:,.2f} exceeds $5,000 threshold",
                    "impact": "high",
                    "feature": "amount",
                    "value": amt,
                })
            elif amt > 1000:
                reasons.append({
                    "code": "ELEVATED_AMOUNT",
                    "description": f"Transaction amount ${amt:,.2f} is above average",
                    "impact": "medium",
                    "feature": "amount",
                    "value": amt,
                })
        except (TypeError, ValueError):
            pass

    for key in ["txn_count_1h", "txn_count_24h", "distinct_ip_1h"]:
        val = features.get(key)
        if val is not None:
            try:
                v = float(val)
                if v > 10:
                    reasons.append({
                        "code": f"HIGH_{key.upper()}",
                        "description": f"{key} = {v} (elevated velocity)",
                        "impact": "high",
                        "feature": key,
                        "value": v,
                    })
            except (TypeError, ValueError):
                pass

    for sig_key, (code, desc) in _SIGNAL_EXPLANATIONS.items():
        if features.get(sig_key) is True:
            reasons.append({
                "code": code,
                "description": desc,
                "impact": "high",
                "feature": sig_key,
                "value": True,
            })

    if adaptive_contributions:
        for contrib in adaptive_contributions[:5]:
            reasons.append({
                "code": f"ANOMALY_{contrib['feature'].upper()}",
                "description": (
                    f"{contrib['feature']} value {contrib['value']} deviates from "
                    f"expected {contrib['expected_mean']} (z={contrib['z_score']})"
                ),
                "impact": "high" if contrib["z_score"] > 3 else "medium",
                "feature": contrib["feature"],
                "value": contrib["value"],
            })

    if score >= 80:
        reasons.insert(0, {
            "code": "CRITICAL_RISK",
            "description": f"Overall risk score {score:.0f}/100 — critical risk level",
            "impact": "critical",
        })
    elif score >= 50:
        reasons.insert(0, {
            "code": "ELEVATED_RISK",
            "description": f"Overall risk score {score:.0f}/100 — elevated risk, manual review recommended",
            "impact": "high",
        })

    return reasons
