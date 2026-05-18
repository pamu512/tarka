"""Regional risk toggles — blacklist sub-regions during attack waves (Prompt 187)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

ATTACK_WAVE_WARN = 65
ATTACK_WAVE_CRITICAL = 80


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# tenant_id -> sub_region_id -> { blacklisted, updated_at, updated_by }
_TOGGLE_STATE: dict[str, dict[str, dict[str, Any]]] = {}


def _catalog() -> list[dict[str, Any]]:
    """Demo sub-regions with synthetic attack-wave intensity."""
    return [
        {
            "sub_region_id": "in-mh-mumbai",
            "country_code": "IN",
            "country_name": "India",
            "label": "Maharashtra — Mumbai metro",
            "attack_wave_score": 78,
            "signals": ["credential_stuffing_spike", "mule_cashout_cluster"],
            "incidents_24h": 142,
        },
        {
            "sub_region_id": "in-ka-bengaluru",
            "country_code": "IN",
            "country_name": "India",
            "label": "Karnataka — Bengaluru tech corridor",
            "attack_wave_score": 52,
            "signals": ["sim_swap_reports"],
            "incidents_24h": 38,
        },
        {
            "sub_region_id": "ng-la-lagos",
            "country_code": "NG",
            "country_name": "Nigeria",
            "label": "Lagos — Lekki / Victoria Island",
            "attack_wave_score": 88,
            "signals": ["romance_scam_ring", "synthetic_identity_burst"],
            "incidents_24h": 96,
        },
        {
            "sub_region_id": "br-sp-interior",
            "country_code": "BR",
            "country_name": "Brazil",
            "label": "São Paulo — ABC interior",
            "attack_wave_score": 71,
            "signals": ["pix_mule_velocity"],
            "incidents_24h": 67,
        },
        {
            "sub_region_id": "us-fl-miami",
            "country_code": "US",
            "country_name": "United States",
            "label": "Florida — Miami-Dade",
            "attack_wave_score": 61,
            "signals": ["stolen_card_testing"],
            "incidents_24h": 54,
        },
        {
            "sub_region_id": "ph-ncr-manila",
            "country_code": "PH",
            "country_name": "Philippines",
            "label": "NCR — Metro Manila",
            "attack_wave_score": 84,
            "signals": ["bpo_fraud_collusion", "account_farming"],
            "incidents_24h": 118,
        },
        {
            "sub_region_id": "gb-lon-east",
            "country_code": "GB",
            "country_name": "United Kingdom",
            "label": "London — East End corridor",
            "attack_wave_score": 48,
            "signals": ["low_grade_phishing"],
            "incidents_24h": 22,
        },
        {
            "sub_region_id": "vn-hcm-district7",
            "country_code": "VN",
            "country_name": "Vietnam",
            "label": "Ho Chi Minh — District 7",
            "attack_wave_score": 73,
            "signals": ["marketplace_refund_abuse"],
            "incidents_24h": 49,
        },
    ]


def _default_blacklisted(score: int) -> bool:
    return score >= ATTACK_WAVE_CRITICAL


def _tier(score: int) -> str:
    if score >= ATTACK_WAVE_CRITICAL:
        return "critical"
    if score >= ATTACK_WAVE_WARN:
        return "elevated"
    return "normal"


def _get_toggle(tenant_id: str, sub_region_id: str, *, default_score: int) -> dict[str, Any]:
    tid = tenant_id.strip() or "demo"
    sid = sub_region_id.strip()
    tenant = _TOGGLE_STATE.setdefault(tid, {})
    if sid not in tenant:
        tenant[sid] = {
            "blacklisted": _default_blacklisted(default_score),
            "updated_at": None,
            "updated_by": None,
        }
    return tenant[sid]


def set_sub_region_blacklist(
    *,
    tenant_id: str,
    sub_region_id: str,
    blacklisted: bool,
    updated_by: str = "analyst",
) -> dict[str, Any] | None:
    tid = (tenant_id or "demo").strip() or "demo"
    catalog = {r["sub_region_id"]: r for r in _catalog()}
    base = catalog.get(sub_region_id.strip())
    if base is None:
        return None
    toggle = _get_toggle(tid, base["sub_region_id"], default_score=int(base["attack_wave_score"]))
    toggle["blacklisted"] = bool(blacklisted)
    toggle["updated_at"] = _now_iso()
    toggle["updated_by"] = updated_by
    return build_sub_region_row(tid, base, toggle)


def build_sub_region_row(
    tenant_id: str,
    base: dict[str, Any],
    toggle: dict[str, Any],
) -> dict[str, Any]:
    score = int(base["attack_wave_score"])
    return {
        "sub_region_id": base["sub_region_id"],
        "country_code": base["country_code"],
        "country_name": base["country_name"],
        "label": base["label"],
        "attack_wave_score": score,
        "attack_tier": _tier(score),
        "signals": list(base.get("signals") or []),
        "incidents_24h": int(base.get("incidents_24h") or 0),
        "blacklisted": bool(toggle.get("blacklisted")),
        "updated_at": toggle.get("updated_at"),
        "updated_by": toggle.get("updated_by"),
        "policy_effect": "block_new_onboarding_and_payouts" if toggle.get("blacklisted") else "monitor_only",
    }


def build_regional_risk_payload(*, tenant_id: str) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    rows = []
    for base in _catalog():
        toggle = _get_toggle(tid, base["sub_region_id"], default_score=int(base["attack_wave_score"]))
        rows.append(build_sub_region_row(tid, base, toggle))

    rows_sorted = sorted(
        rows,
        key=lambda r: (
            0 if r["blacklisted"] else 1,
            -int(r["attack_wave_score"]),
            str(r["country_code"]),
        ),
    )

    by_country: dict[str, list[dict[str, Any]]] = {}
    for r in rows_sorted:
        by_country.setdefault(str(r["country_code"]), []).append(r)

    country_groups = [
        {
            "country_code": code,
            "country_name": items[0]["country_name"],
            "sub_regions": items,
            "blacklisted_count": sum(1 for i in items if i["blacklisted"]),
        }
        for code, items in sorted(by_country.items(), key=lambda x: x[0])
    ]

    blacklisted = [r for r in rows if r["blacklisted"]]
    critical_waves = [r for r in rows if r["attack_tier"] == "critical"]

    return {
        "tenant_id": tid,
        "updated_at": _now_iso(),
        "source": "demo_aggregate",
        "thresholds": {
            "attack_wave_warn": ATTACK_WAVE_WARN,
            "attack_wave_critical": ATTACK_WAVE_CRITICAL,
        },
        "summary": {
            "sub_region_count": len(rows),
            "blacklisted_count": len(blacklisted),
            "elevated_wave_count": sum(1 for r in rows if r["attack_tier"] == "elevated"),
            "critical_wave_count": len(critical_waves),
        },
        "signals": [
            f"{len(blacklisted)} sub-region(s) blacklisted for tenant {tid}",
        ]
        if blacklisted
        else [],
        "sub_regions": rows_sorted,
        "country_groups": country_groups,
    }
