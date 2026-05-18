"""Per–API-key rate limit shields with in-process token buckets (Prompt 176)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_RPM = 600
DEFAULT_BURST = 50
MIN_RPM = 10
MAX_RPM = 100_000
MIN_BURST = 1
MAX_BURST = 10_000
THROTTLE_COOLDOWN_SEC = 60.0


@dataclass
class _BucketState:
    tokens: float
    last_refill: float
    throttled_until: float = 0.0
    rejected_count: int = 0


_buckets: dict[str, _BucketState] = {}


def _clamp_rpm(value: int) -> int:
    return max(MIN_RPM, min(MAX_RPM, int(value)))


def _clamp_burst(value: int) -> int:
    return max(MIN_BURST, min(MAX_BURST, int(value)))


def normalize_shield_config(
    *,
    enabled: bool | None = None,
    requests_per_minute: int | None = None,
    burst: int | None = None,
) -> dict[str, Any]:
    return {
        "enabled": True if enabled is None else bool(enabled),
        "requests_per_minute": _clamp_rpm(requests_per_minute if requests_per_minute is not None else DEFAULT_RPM),
        "burst": _clamp_burst(burst if burst is not None else DEFAULT_BURST),
    }


def _bucket(key_id: str) -> _BucketState:
    st = _buckets.get(key_id)
    if st is None:
        st = _BucketState(tokens=float(DEFAULT_BURST), last_refill=time.monotonic())
        _buckets[key_id] = st
    return st


def reset_bucket(key_id: str) -> None:
    _buckets.pop(key_id, None)


@dataclass
class RateLimitDecision:
    allowed: bool
    requests_in_window: int
    remaining: int
    throttled: bool
    throttled_until: str | None = None
    limit_rpm: int = DEFAULT_RPM
    burst: int = DEFAULT_BURST


def evaluate_rate_limit(
    key_id: str,
    *,
    enabled: bool,
    rpm: int,
    burst: int,
    consume: bool = True,
) -> RateLimitDecision:
    """Token-bucket check for one SDK API key (in-process; single replica)."""
    rpm = _clamp_rpm(rpm)
    burst = _clamp_burst(burst)
    if not enabled:
        return RateLimitDecision(
            allowed=True,
            requests_in_window=0,
            remaining=burst,
            throttled=False,
            limit_rpm=rpm,
            burst=burst,
        )

    now = time.monotonic()
    st = _bucket(key_id)
    if st.throttled_until > now:
        if consume:
            st.rejected_count += 1
        used = max(0, burst - int(st.tokens))
        return RateLimitDecision(
            allowed=False,
            requests_in_window=used,
            remaining=0,
            throttled=True,
            throttled_until=_iso_from_mono(st.throttled_until),
            limit_rpm=rpm,
            burst=burst,
        )

    refill_rate = rpm / 60.0
    elapsed = max(0.0, now - st.last_refill)
    st.tokens = min(float(burst), st.tokens + elapsed * refill_rate)
    st.last_refill = now

    if st.tokens < 1.0:
        st.throttled_until = now + THROTTLE_COOLDOWN_SEC
        if consume:
            st.rejected_count += 1
        used = burst
        return RateLimitDecision(
            allowed=False,
            requests_in_window=used,
            remaining=0,
            throttled=True,
            throttled_until=_iso_from_mono(st.throttled_until),
            limit_rpm=rpm,
            burst=burst,
        )

    if consume:
        st.tokens -= 1.0
    remaining = max(0, int(st.tokens))
    used = burst - remaining
    return RateLimitDecision(
        allowed=True,
        requests_in_window=used,
        remaining=remaining,
        throttled=False,
        limit_rpm=rpm,
        burst=burst,
    )


def _iso_from_mono(ts: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(time.time() + (ts - time.monotonic()), tz=UTC).isoformat()


def shield_live_stats(
    key_id: str,
    *,
    enabled: bool,
    rpm: int,
    burst: int,
) -> dict[str, Any]:
    decision = evaluate_rate_limit(key_id, enabled=enabled, rpm=rpm, burst=burst, consume=False)
    st = _bucket(key_id)
    return {
        "requests_in_window": decision.requests_in_window,
        "remaining": decision.remaining,
        "throttled": decision.throttled,
        "throttled_until": decision.throttled_until,
        "rejected_total": st.rejected_count,
    }


def _shield_config_from_row(row: Any) -> dict[str, Any]:
    enabled = bool(getattr(row, "rate_limit_enabled", True))
    rpm = _clamp_rpm(int(getattr(row, "rate_limit_rpm", None) or DEFAULT_RPM))
    burst = _clamp_burst(int(getattr(row, "rate_limit_burst", None) or DEFAULT_BURST))
    return {"enabled": enabled, "requests_per_minute": rpm, "burst": burst}


def shield_item_from_row(row: Any) -> dict[str, Any]:
    cfg = _shield_config_from_row(row)
    kid = str(row.id)
    live = shield_live_stats(kid, enabled=cfg["enabled"], rpm=cfg["requests_per_minute"], burst=cfg["burst"])
    return {
        "key_id": kid,
        "tenant_id": row.tenant_id,
        "platform": row.platform,
        "label": row.label,
        "key_prefix": row.key_prefix,
        "status": row.status,
        "shield": cfg,
        "live": live,
    }


async def list_rate_limit_shields(session: AsyncSession, *, tenant_id: str) -> list[dict[str, Any]]:
    from integration_ingress.models import MarketplaceSdkApiKey

    tid = (tenant_id or "demo").strip() or "demo"
    rows = (
        await session.scalars(
            select(MarketplaceSdkApiKey)
            .where(MarketplaceSdkApiKey.tenant_id == tid)
            .order_by(MarketplaceSdkApiKey.created_at.desc()),
        )
    ).all()
    return [shield_item_from_row(r) for r in rows]


async def update_rate_limit_shield(
    session: AsyncSession,
    *,
    tenant_id: str,
    key_id: str,
    enabled: bool | None = None,
    requests_per_minute: int | None = None,
    burst: int | None = None,
) -> dict[str, Any] | None:
    from integration_ingress.models import MarketplaceSdkApiKey

    tid = (tenant_id or "demo").strip() or "demo"
    try:
        kid = uuid.UUID(str(key_id))
    except ValueError:
        return None
    row = await session.scalar(
        select(MarketplaceSdkApiKey).where(
            MarketplaceSdkApiKey.id == kid,
            MarketplaceSdkApiKey.tenant_id == tid,
        ),
    )
    if row is None:
        return None
    if enabled is not None:
        row.rate_limit_enabled = bool(enabled)
    if requests_per_minute is not None:
        row.rate_limit_rpm = _clamp_rpm(requests_per_minute)
    if burst is not None:
        row.rate_limit_burst = _clamp_burst(burst)
    await session.commit()
    await session.refresh(row)
    reset_bucket(str(row.id))
    return shield_item_from_row(row)


def consume_for_verified_key(key_id: str, *, enabled: bool, rpm: int, burst: int) -> RateLimitDecision:
    return evaluate_rate_limit(key_id, enabled=enabled, rpm=rpm, burst=burst, consume=True)
