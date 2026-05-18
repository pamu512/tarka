"""Build ``EvaluateRequest``-shaped JSON bodies from suite defaults and per-case overrides."""

from __future__ import annotations

import copy
from typing import Any, Mapping


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if (
            k in out
            and isinstance(out[k], dict)
            and isinstance(v, Mapping)
        ):
            out[k] = deep_merge(out[k], dict(v))
        else:
            out[k] = copy.deepcopy(v)
    return out


def merge_signals_into_device_context(
    body: dict[str, Any],
    signals: Mapping[str, Any],
    *,
    default_device_id: str,
    default_platform: str,
) -> None:
    """Merge ``signals`` into ``device_context.signals``, creating ``device_context`` if absent."""
    if not signals:
        return
    dc = body.get("device_context")
    if dc is None:
        body["device_context"] = {
            "device_id": default_device_id,
            "platform": default_platform,
            "signals": {},
        }
        dc = body["device_context"]
    elif not isinstance(dc, dict):
        raise ValueError("device_context must be an object when input_signals is set")
    else:
        dc.setdefault("device_id", default_device_id)
        dc.setdefault("platform", default_platform)
    sig = dc.get("signals")
    if sig is None:
        dc["signals"] = {}
        sig = dc["signals"]
    if not isinstance(sig, dict):
        raise ValueError("device_context.signals must be an object")
    for k, v in signals.items():
        sig.setdefault(k, v)


def build_evaluate_body(
    case: Mapping[str, Any],
    defaults: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the HTTP JSON body for ``POST .../evaluate``."""
    base = copy.deepcopy(dict(defaults.get("request") or {}))
    req_override = case.get("request")
    if isinstance(req_override, Mapping):
        body = deep_merge(base, dict(req_override))
    else:
        body = base

    sigs = case.get("input_signals")
    if sigs is not None:
        if not isinstance(sigs, Mapping):
            raise ValueError("input_signals must be a JSON object")
        merge_signals_into_device_context(
            body,
            sigs,
            default_device_id=str(
                defaults.get("default_device_id") or body.get("default_device_id") or "tarka-test-device"
            ),
            default_platform=str(
                defaults.get("default_platform") or "web"
            ),
        )

    body.setdefault("tenant_id", "default")
    body.setdefault("event_type", "payment")
    body.setdefault("entity_id", "tarka-test-entity")
    body.setdefault("payload", {})
    body.setdefault("metadata", {})
    body.setdefault("region", "global")
    return body
