"""Social engineering monitor — credential changes after high-value listings (Prompt 184)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_HIGH_VALUE_LISTING_USD = 5000
DEFAULT_CREDENTIAL_WINDOW_MINUTES = 10
DEFAULT_SCAN_LIMIT = 40


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


_CONFIG_BY_TENANT: dict[str, dict[str, Any]] = {}


def get_social_engineering_config(tenant_id: str) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    if tid not in _CONFIG_BY_TENANT:
        _CONFIG_BY_TENANT[tid] = {
            "high_value_listing_usd": DEFAULT_HIGH_VALUE_LISTING_USD,
            "credential_change_window_minutes": DEFAULT_CREDENTIAL_WINDOW_MINUTES,
            "require_email_and_password_change": True,
        }
    return dict(_CONFIG_BY_TENANT[tid])


def update_social_engineering_config(
    *,
    tenant_id: str,
    high_value_listing_usd: int | None = None,
    credential_change_window_minutes: int | None = None,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    cfg = get_social_engineering_config(tid)
    if high_value_listing_usd is not None:
        cfg["high_value_listing_usd"] = max(500, min(int(high_value_listing_usd), 5_000_000))
    if credential_change_window_minutes is not None:
        cfg["credential_change_window_minutes"] = max(
            1, min(int(credential_change_window_minutes), 120)
        )
    _CONFIG_BY_TENANT[tid] = cfg
    return dict(cfg)


def _is_flagged(
    *,
    listing_value_usd: float,
    minutes_email_after_listing: float | None,
    minutes_password_after_listing: float | None,
    cfg: dict[str, Any],
) -> tuple[bool, list[str]]:
    threshold = float(cfg.get("high_value_listing_usd") or DEFAULT_HIGH_VALUE_LISTING_USD)
    window = float(cfg.get("credential_change_window_minutes") or DEFAULT_CREDENTIAL_WINDOW_MINUTES)
    signals: list[str] = []

    if listing_value_usd < threshold:
        return False, signals

    email_ok = (
        minutes_email_after_listing is not None and 0 <= minutes_email_after_listing <= window
    )
    password_ok = (
        minutes_password_after_listing is not None and 0 <= minutes_password_after_listing <= window
    )

    if email_ok:
        signals.append("email_change_within_window_of_high_value_listing")
    if password_ok:
        signals.append("password_change_within_window_of_high_value_listing")

    require_both = bool(cfg.get("require_email_and_password_change", True))
    if require_both:
        flagged = email_ok and password_ok
        if flagged:
            signals.append("social_engineering_credential_burst")
    else:
        flagged = email_ok or password_ok

    return flagged, signals


def _account_row(index: int, *, tenant_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    seed = hashlib.sha256(f"{tenant_id}:social_eng:{index}".encode()).hexdigest()
    profile = int(seed[0:2], 16) % 8

    listing_at = datetime.now(UTC) - timedelta(hours=index * 4 + 2)
    listing_value = [1200, 8900, 15000, 6200, 450, 22000, 7800, 3100][profile]

    if profile in (1, 2, 3, 6):
        email_delta = 3.5 + (int(seed[2:4], 16) % 50) / 10
        password_delta = 6.0 + (int(seed[4:6], 16) % 30) / 10
    elif profile == 5:
        email_delta = 45.0
        password_delta = 50.0
    else:
        email_delta = None
        password_delta = 25.0

    email_at = listing_at + timedelta(minutes=email_delta) if email_delta is not None else None
    password_at = (
        listing_at + timedelta(minutes=password_delta) if password_delta is not None else None
    )

    flagged, signals = _is_flagged(
        listing_value_usd=float(listing_value),
        minutes_email_after_listing=email_delta,
        minutes_password_after_listing=password_delta,
        cfg=cfg,
    )

    titles = [
        "Vintage watch collection",
        "Commercial espresso machine",
        "EV battery pack (used)",
        "Designer furniture lot",
        "Used textbooks bundle",
        "Luxury handbag — limited edition",
        "Mining rig GPU array",
        "Antique piano",
    ]

    return {
        "account_id": f"acct_{seed[:10]}",
        "user_id": f"user_{seed[10:18]}",
        "display_name": f"Seller account {index + 1}",
        "listing_id": f"listing_{seed[18:26]}",
        "listing_title": titles[profile],
        "listing_value_usd": float(listing_value),
        "listing_posted_at": listing_at.isoformat(),
        "email_changed_at": email_at.isoformat() if email_at else None,
        "password_changed_at": password_at.isoformat() if password_at else None,
        "minutes_listing_to_email_change": email_delta,
        "minutes_listing_to_password_change": password_delta,
        "is_social_engineering_flag": flagged,
        "signals": signals,
        "risk_score": 92 if flagged else max(12, 40 - profile * 4),
    }


def build_social_engineering_payload(
    *,
    tenant_id: str,
    limit: int = DEFAULT_SCAN_LIMIT,
    only_flagged: bool = False,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    lim = max(5, min(int(limit), 150))
    cfg = get_social_engineering_config(tid)

    all_accounts = [_account_row(i, tenant_id=tid, cfg=cfg) for i in range(lim)]
    accounts = (
        [a for a in all_accounts if a["is_social_engineering_flag"]]
        if only_flagged
        else all_accounts
    )

    accounts_sorted = sorted(
        accounts,
        key=lambda a: (
            0 if a["is_social_engineering_flag"] else 1,
            -int(a["risk_score"]),
            str(a["account_id"]),
        ),
    )

    flagged = [a for a in all_accounts if a["is_social_engineering_flag"]]
    window = int(cfg["credential_change_window_minutes"])

    platform_signals: list[str] = []
    if flagged:
        platform_signals.append(
            f"{len(flagged)} account(s) changed email and password within {window}m of a high-value listing",
        )

    return {
        "tenant_id": tid,
        "updated_at": _now_iso(),
        "source": "demo_aggregate",
        "config": cfg,
        "summary": {
            "scanned_accounts": len(all_accounts),
            "flagged_accounts": len(flagged),
            "high_value_threshold_usd": float(cfg["high_value_listing_usd"]),
            "credential_window_minutes": window,
        },
        "signals": platform_signals,
        "accounts": accounts_sorted,
    }
