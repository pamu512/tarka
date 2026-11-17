from __future__ import annotations

from typing import Any

_BIOMETRIC_GROUPS = ("typing", "mouse", "session", "bot_indicators")
_TAG = "device_intelligence:unavailable"


def device_ip_for_velocity(payload: dict | None, signals: dict | None) -> str:
    candidates: list[Any] = []
    if isinstance(payload, dict):
        candidates.append(payload.get("ip_address"))
    if isinstance(signals, dict):
        candidates.append(signals.get("ip_address"))
    for raw in candidates:
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def _device_id(device_id: str | None) -> str:
    if not isinstance(device_id, str):
        return ""
    return device_id.strip()


def _armed(store: Any, device_id: str | None, shadow: bool) -> str:
    if shadow or getattr(store, "_client", None) is None:
        return ""
    return _device_id(device_id)


def _mark(degrade_tags: list[str]) -> None:
    if _TAG not in degrade_tags:
        degrade_tags.append(_TAG)


async def apply_prior_device_reputation(
    features: dict,
    degrade_tags: list[str],
    *,
    store: Any,
    tenant_id: str,
    device_id: str | None,
    shadow: bool,
) -> None:
    did = _armed(store, device_id, shadow)
    if not did:
        return
    try:
        row = await store.get_device_reputation(tenant_id, did)
    except Exception:
        _mark(degrade_tags)
        return
    if row is None:
        return
    features["device_reputation_score"] = row.calculate_risk_score()


async def record_device_intelligence_outcome(
    degrade_tags: list[str],
    *,
    store: Any,
    tenant_id: str,
    entity_id: str,
    device_id: str | None,
    decision: str,
    signals: dict | None,
    ip: str | None,
    shadow: bool,
) -> None:
    did = _armed(store, device_id, shadow)
    if not did:
        return
    try:
        await store.update_device_reputation(
            tenant_id, did, decision, is_fraud_confirmed=False
        )
        if isinstance(signals, dict) and any(
            isinstance(signals.get(key), dict) for key in _BIOMETRIC_GROUPS
        ):
            await store.record_biometrics(tenant_id, entity_id, did, signals)
        await store.record_consortium_device(did, tenant_id, entity_id)
        if isinstance(ip, str) and ip.strip():
            await store.record_device_ip_velocity(did, ip.strip(), tenant_id)
    except Exception:
        _mark(degrade_tags)
