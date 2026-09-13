"""Read anumana velocity counters + session dropoff flags into evaluate features."""

from __future__ import annotations

import hashlib
import time
from typing import Any

ANUMANA_VEL_PREFIX = "anumana:velocity"
ANUMANA_SESSION_RISK_PREFIX = "anumana:session_risk"
_MEMBER_SEP = "\x1f"
_RISK_VALUE = "HIGH_RISK_DROPOFF"

_WINDOWS: tuple[tuple[str, int], ...] = ("1m", 60), ("5m", 300), ("1h", 3600)


def anumana_device_token(canvas: str | None) -> str | None:
    """SHA-256 of the canvas fingerprint — mirrors orchestrator device_hash_token."""
    if not canvas or not canvas.strip():
        return None
    return hashlib.sha256(canvas.strip().encode("utf-8")).hexdigest()


def _tenant_seg(tenant_id: str | None) -> str:
    t = (tenant_id or "").strip()
    if not t or len(t) > 128 or "\x00" in t:
        return "_"
    return t


def _bucket(now_unix: int, win_sec: int) -> int:
    return now_unix // win_sec


def _device_keys(tenant_id: str | None, token: str, now: int) -> list[tuple[str, str]]:
    return [
        (
            f"{ANUMANA_VEL_PREFIX}:t:{_tenant_seg(tenant_id)}:device:{win}:{token}:{_bucket(now, ws)}",
            win,
        )
        for win, ws in _WINDOWS
    ]


async def anumana_velocity_features(
    redis_client: Any,
    *,
    tenant_id: str | None,
    canvas: str | None,
    now_unix: int | None = None,
) -> dict[str, int]:
    """MGET device velocity counters for current buckets; empty dict on any failure."""
    token = anumana_device_token(canvas)
    if redis_client is None or token is None:
        return {}
    now = int(now_unix if now_unix is not None else time.time())
    pairs = _device_keys(tenant_id, token, now)
    try:
        raw = await redis_client.mget([k for k, _ in pairs])
    except Exception as e:  # pragma: no cover — network
        return {}
    out: dict[str, int] = {}
    for (key, win), val in zip(pairs, raw):
        if val is None:
            continue
        try:
            out[f"anumana_velocity_{win}"] = int(val)
        except (TypeError, ValueError):
            continue
    return out


def session_risk_key(tenant_id: str | None, session_id: str) -> str:
    return f"{ANUMANA_SESSION_RISK_PREFIX}:{_tenant_seg(tenant_id)}{_MEMBER_SEP}{session_id.strip()}"


async def merge_anumana_signals(
    redis_client: Any,
    *,
    tenant_id: str | None,
    canvas: str | None,
    session_id: str | None,
    features: dict[str, Any],
    degrade_tags: list[str] | None = None,
    now_unix: int | None = None,
) -> None:
    """Merge velocity counters + session dropoff flag into *features* in place.

    Fail-open: any Redis error leaves features untouched — anumana signals are
    additive, never blocking. Emits no invented values (missing keys stay
    absent).
    """
    if redis_client is None:
        return
    vel = await anumana_velocity_features(
        redis_client, tenant_id=tenant_id, canvas=canvas, now_unix=now_unix
    )
    for k, v in vel.items():
        features.setdefault(k, v)
    if vel and degrade_tags is not None and "sdk:anumana_velocity" not in degrade_tags:
        degrade_tags.append("sdk:anumana_velocity")
    if session_id and session_id.strip():
        try:
            flag = await redis_client.get(session_risk_key(tenant_id, session_id))
        except Exception:  # pragma: no cover — network
            flag = None
        if flag == _RISK_VALUE:
            features["session_dropoff_risk"] = True
            if degrade_tags is not None and "sdk:session_dropoff" not in degrade_tags:
                degrade_tags.append("sdk:session_dropoff")
