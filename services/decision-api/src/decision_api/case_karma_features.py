"""Case karma features — host-supplied metadata/payload only.

No LIVE dispute network required. The historical optional case-api karma
fetch (GET /v1/entities/{id}/karma) targeted a route no service ever
served — it failed soft to None in every real deployment while tests
mocked the transport green. The hop is removed: rates come from host
metadata/payload or not at all.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("decision-api.case_karma_features")

_RATE_KEYS = (
    "repeat_refund_rate_30d",
    "dispute_loss_rate_30d",
)
_COUNT_KEYS = ("seller_case_count_90d",)


def _safe_float(val: Any) -> float | None:
    if isinstance(val, bool) or val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    if isinstance(val, bool) or val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _pick(sources: tuple[dict[str, Any], ...], key: str) -> Any:
    for src in sources:
        if key in src and src[key] is not None:
            return src[key]
    return None


def apply_case_karma_from_sources(
    features: dict[str, Any],
    *sources: dict[str, Any],
) -> None:
    """Merge karma fields from metadata/payload/case-api JSON into features."""
    srcs = tuple(s for s in sources if isinstance(s, dict))
    for key in _RATE_KEYS:
        val = _safe_float(_pick(srcs, key))
        if val is None:
            continue
        features[key] = max(0.0, min(1.0, val))
    for key in _COUNT_KEYS:
        val = _safe_int(_pick(srcs, key))
        if val is None:
            continue
        features[key] = max(0, val)

    rr = features.get("repeat_refund_rate_30d")
    if isinstance(rr, (int, float)):
        features["repeat_refund_high"] = float(rr) >= 0.35
    dl = features.get("dispute_loss_rate_30d")
    if isinstance(dl, (int, float)):
        features["dispute_loss_high"] = float(dl) >= 0.40
    sc = features.get("seller_case_count_90d")
    if isinstance(sc, int):
        features["seller_case_volume_high"] = sc >= 8

    if features.get("repeat_refund_high") or features.get("dispute_loss_high"):
        features["case_karma_high"] = True


async def apply_case_karma_features(
    features: dict[str, Any],
    *,
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    http: Any = None,  # retained for call-site compat; no network hops
    tenant_id: str = "",
    entity_id: str = "",
) -> dict[str, Any] | None:
    """Metadata/payload karma only; no network hops.

    ``http``/``tenant_id``/``entity_id`` are accepted for call-site
    compatibility and intentionally unused.
    """
    pl = payload if isinstance(payload, dict) else {}
    meta = metadata if isinstance(metadata, dict) else {}
    karma_block = (
        meta.get("case_karma") if isinstance(meta.get("case_karma"), dict) else {}
    )
    apply_case_karma_from_sources(features, karma_block, meta, pl)

    if any(k in features for k in _RATE_KEYS + _COUNT_KEYS):
        return {
            "schema_id": "tarka.case_karma/v1",
            "source": "metadata",
            "live_claim_allowed": False,
            "fields": [k for k in _RATE_KEYS + _COUNT_KEYS if k in features],
        }
    return None
