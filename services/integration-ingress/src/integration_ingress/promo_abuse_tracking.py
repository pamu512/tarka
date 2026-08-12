"""Promo abuse tracking — unique users per coupon code (Prompt 180, Track B3 durable)."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from integration_ingress.promo_abuse_store import list_redemptions

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


def _aggregate_users(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_user: dict[str, dict[str, Any]] = {}
    for row in rows:
        uid = str(row.get("user_id") or "")
        if not uid:
            continue
        redeemed_raw = row.get("redeemed_at")
        try:
            redeemed_ts = datetime.fromisoformat(str(redeemed_raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            redeemed_ts = datetime.now(UTC)
        if redeemed_ts.tzinfo is None:
            redeemed_ts = redeemed_ts.replace(tzinfo=UTC)

        existing = by_user.get(uid)
        flags = list(row.get("flags") or [])
        order_total = row.get("order_total")
        if existing is None:
            by_user[uid] = {
                "user_id": uid,
                "display_name": row.get("display_name") or uid,
                "redemption_count": 1,
                "first_redeemed_at": redeemed_ts.isoformat(),
                "last_redeemed_at": redeemed_ts.isoformat(),
                "device_id": row.get("device_id"),
                "ip_hint": row.get("ip_hint"),
                "order_total_usd": round(float(order_total), 2)
                if order_total is not None
                else None,
                "flags": list(flags),
            }
            continue

        existing["redemption_count"] = int(existing["redemption_count"]) + 1
        if redeemed_ts.isoformat() < str(existing["first_redeemed_at"]):
            existing["first_redeemed_at"] = redeemed_ts.isoformat()
        if redeemed_ts.isoformat() > str(existing["last_redeemed_at"]):
            existing["last_redeemed_at"] = redeemed_ts.isoformat()
            if row.get("device_id"):
                existing["device_id"] = row.get("device_id")
            if row.get("ip_hint"):
                existing["ip_hint"] = row.get("ip_hint")
            if order_total is not None:
                existing["order_total_usd"] = round(float(order_total), 2)
        merged_flags = set(existing.get("flags") or []) | set(flags)
        existing["flags"] = sorted(merged_flags)
        if int(existing["redemption_count"]) > 1 and "multi_redeem" not in existing["flags"]:
            existing["flags"].append("multi_redeem")

    device_counts: dict[str, int] = defaultdict(int)
    for user in by_user.values():
        dev = str(user.get("device_id") or "")
        if dev:
            device_counts[dev] += 1
    for user in by_user.values():
        dev = str(user.get("device_id") or "")
        if dev and device_counts[dev] >= 3 and "shared_device_cluster" not in user["flags"]:
            user["flags"].append("shared_device_cluster")

    return list(by_user.values())


def _daily_series(users: list[dict[str, Any]], days: int = 7) -> list[dict[str, Any]]:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=days - 1
    )
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


async def build_promo_abuse_payload(
    session: AsyncSession,
    *,
    tenant_id: str,
    coupon_code: str = DEFAULT_COUPON,
    window_days: int = 7,
) -> dict[str, Any]:
    code = (coupon_code or DEFAULT_COUPON).strip().upper() or DEFAULT_COUPON
    tid = (tenant_id or "demo").strip() or "demo"
    days = max(1, min(int(window_days), 90))

    rows = await list_redemptions(
        session,
        tenant_id=tid,
        coupon_code=code,
        window_days=days,
    )
    users = _aggregate_users(rows)
    total_redemptions = sum(int(u.get("redemption_count") or 0) for u in users)
    devices = {str(u.get("device_id")) for u in users if u.get("device_id")}
    shared_device_users = sum(1 for u in users if "shared_device_cluster" in (u.get("flags") or []))
    warn = DEFAULT_WARN_UNIQUE_USERS
    critical = DEFAULT_CRITICAL_UNIQUE_USERS
    risk = _risk_level(len(users), warn=warn, critical=critical)

    signals: list[str] = []
    if len(users) >= warn:
        signals.append(
            f"{len(users)} unique accounts redeemed {code} in {days}d (above {warn} warn threshold)"
        )
    if shared_device_users >= 5:
        signals.append(f"{shared_device_users} users map to high-overlap device clusters")
    if total_redemptions > len(users) + 3:
        signals.append(f"{total_redemptions - len(users)} repeat redemptions beyond first-time use")

    users_sorted = sorted(users, key=lambda u: (-int(u["redemption_count"]), str(u["user_id"])))

    return {
        "tenant_id": tid,
        "coupon_code": code,
        "updated_at": _now_iso(),
        "source": "durable",
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
