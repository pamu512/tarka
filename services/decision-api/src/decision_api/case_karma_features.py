"""Case karma features — metadata-first, optional case-api fetch (fail-soft).

No LIVE dispute network required. Host may inject rates; optional CASE_API_URL
returns the same field shape for offline mocks.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

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


def case_api_config() -> dict[str, Any]:
    url = (
        os.environ.get("CASE_API_URL")
        or os.environ.get("TARKA_CASE_API_URL")
        or ""
    ).strip()
    key = (
        os.environ.get("CASE_API_KEY")
        or os.environ.get("TARKA_CASE_API_KEY")
        or ""
    ).strip()
    return {
        "url": url,
        "api_key": key,
        "configured": bool(url),
        "live_claim_allowed": False,  # karma fetch ≠ LIVE card/dispute network
    }


async def maybe_fetch_case_karma(
    *,
    http: httpx.AsyncClient | None,
    tenant_id: str,
    entity_id: str,
    timeout_seconds: float = 1.5,
) -> dict[str, Any] | None:
    """Optional case-api karma JSON; fail-soft → None."""
    cfg = case_api_config()
    if not cfg["url"] or http is None:
        return None
    url = f"{cfg['url'].rstrip('/')}/v1/entities/{entity_id}/karma"
    headers: dict[str, str] = {}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    try:
        r = await http.get(
            url,
            headers=headers,
            params={"tenant_id": tenant_id},
            timeout=timeout_seconds,
        )
        if r.status_code >= 400:
            return None
        data = r.json() if r.content else {}
        return data if isinstance(data, dict) else None
    except Exception:
        log.debug("case_karma_fetch_failed", exc_info=True)
        return None


async def apply_case_karma_features(
    features: dict[str, Any],
    *,
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    http: httpx.AsyncClient | None = None,
    tenant_id: str = "",
    entity_id: str = "",
) -> dict[str, Any] | None:
    """Metadata-first karma; optional case-api fill for missing rates."""
    pl = payload if isinstance(payload, dict) else {}
    meta = metadata if isinstance(metadata, dict) else {}
    karma_block = meta.get("case_karma") if isinstance(meta.get("case_karma"), dict) else {}
    apply_case_karma_from_sources(features, karma_block, meta, pl)

    need_fetch = any(
        k not in features for k in ("repeat_refund_rate_30d", "dispute_loss_rate_30d")
    )
    evidence: dict[str, Any] | None = None
    if need_fetch and tenant_id and entity_id:
        remote = await maybe_fetch_case_karma(
            http=http, tenant_id=tenant_id, entity_id=entity_id
        )
        if remote:
            apply_case_karma_from_sources(features, remote)
            evidence = {
                "schema_id": "tarka.case_karma/v1",
                "source": "case_api",
                "live_claim_allowed": False,
                "fields": [k for k in _RATE_KEYS + _COUNT_KEYS if k in features],
            }
    if any(k in features for k in _RATE_KEYS + _COUNT_KEYS) and evidence is None:
        evidence = {
            "schema_id": "tarka.case_karma/v1",
            "source": "metadata",
            "live_claim_allowed": False,
            "fields": [k for k in _RATE_KEYS + _COUNT_KEYS if k in features],
        }
    return evidence
