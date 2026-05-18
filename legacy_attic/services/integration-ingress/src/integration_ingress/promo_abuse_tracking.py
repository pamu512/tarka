"""Promo abuse tracking — unique users per coupon code (Prompt 180)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_COUPON = "NEWUSER50"
DEFAULT_WARN_UNIQUE_USERS = 25
DEFAULT_CRITICAL_UNIQUE_USERS = 75


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _risk_level(unique_users: int, *, warn: int, critical: int) -> str:
    if unique_users >= critical:
        return "critical"
    if unique_users >= warn:
        return "elevated"
    return "normal"


def _demo_users_for_coupon(coupon_code: str, count: int) -> list[dict[str, Any]]:
    """Deterministic synthetic redemptions for dashboard demos."""
    code = (coupon_code or DEFAULT_COUPON).strip().upper()
    users: list[dict[str, Any]] = []
    base = datetime.now(UTC) - timedelta(days=7)
    for i in range(count):
        seed = hashlib.sha256(f"{code}:{i}".encode()).hexdigest()
        uid = f"promo_user_{seed[:8]}"
        device_bucket = int(seed[8:10], 16) % 12
        device_id = f"dev_promo_{device_bucket:02d}"
        redemptions = 1 if i % 9 else 2
        first = base + timedelta(hours=i * 3.2)
        last = first + timedelta(hours=redemptions * 0.5)
        flags: list[str] = []
        if device_bucket < 3 and i > 5:
            flags.append("shared_device_cluster")
        if redemptions > 1:
            flags.append("multi_redeem")
        users.append(
            {
                "user_id": uid,
                "display_name": f"Marketplace user {i + 1}",
                "redemption_count": redemptions,
                "first_redeemed_at": first.isoformat(),
                "last_redeemed_at": last.isoformat(),
                "device_id": device_id,
                "ip_hint": f"73.{int(seed[10:12], 16)}.{int(seed[12:14], 16)}.{int(seed[14:16], 16)}",
                "order_total_usd": round(42 + (int(seed[16:20], 16) % 120), 2),
                "flags": flags,
            },
        )
    return users


def _daily_series(users: list[dict[str, Any]], days: int = 7) -> list[dict[str, Any]]:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    buckets: list[dict[str, set[str] | int]] = [
        {"date": (start + timedelta(days=d)).date().isoformat(), "users": set(), "redemptions": 0}
        for d in range(days)
    ]
    for u in users:
        try:
            ts = datetime.fromisoformat(str(u["last_redeemed_at"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        day = ts.astimezone(UTC).date().isoformat()
        for b in buckets:
            if b["date"] == day:
                b["users"].add(str(u["user_id"]))
                b["redemptions"] = int(b["redemptions"]) + int(u.get("redemption_count") or 1)
                break
    return [
        {
            "date": b["date"],
            "unique_users": len(b["users"]),
            "redemptions": int(b["redemptions"]),
        }
        for b in buckets
    ]


def build_promo_abuse_payload(
    *,
    tenant_id: str,
    coupon_code: str = DEFAULT_COUPON,
    window_days: int = 7,
) -> dict[str, Any]:
    code = (coupon_code or DEFAULT_COUPON).strip().upper() or DEFAULT_COUPON
    tid = (tenant_id or "demo").strip() or "demo"
    days = max(1, min(int(window_days), 90))

    if code == DEFAULT_COUPON:
        user_count = 47
    elif code in ("WELCOME10", "FREESHIP"):
        user_count = 18
    else:
        digest = int(hashlib.sha256(code.encode()).hexdigest()[:6], 16)
        user_count = 8 + (digest % 35)

    users = _demo_users_for_coupon(code, user_count)
    total_redemptions = sum(int(u.get("redemption_count") or 0) for u in users)
    devices = {str(u.get("device_id")) for u in users if u.get("device_id")}
    shared_device_users = sum(
        1 for u in users if "shared_device_cluster" in (u.get("flags") or [])
    )
    warn = DEFAULT_WARN_UNIQUE_USERS
    critical = DEFAULT_CRITICAL_UNIQUE_USERS
    risk = _risk_level(len(users), warn=warn, critical=critical)

    signals: list[str] = []
    if len(users) >= warn:
        signals.append(f"{len(users)} unique accounts redeemed {code} in {days}d (above {warn} warn threshold)")
    if shared_device_users >= 5:
        signals.append(f"{shared_device_users} users map to high-overlap device clusters")
    if total_redemptions > len(users) + 3:
        signals.append(f"{total_redemptions - len(users)} repeat redemptions beyond first-time use")

    users_sorted = sorted(users, key=lambda u: (-int(u["redemption_count"]), str(u["user_id"])))

    return {
        "tenant_id": tid,
        "coupon_code": code,
        "updated_at": _now_iso(),
        "source": "demo_aggregate",
        "window_days": days,
        "summary": {
            "unique_users": len(users),
            "total_redemptions": total_redemptions,
            "distinct_devices": len(devices),
            "users_with_shared_device_flags": shared_device_users,
            "abuse_risk": risk,
        },
        "thresholds": {
            "warn_unique_users": warn,
            "critical_unique_users": critical,
        },
        "signals": signals,
        "daily_series": _daily_series(users, days=days),
        "users": users_sorted,
    }
