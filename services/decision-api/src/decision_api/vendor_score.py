"""Optional buyer-configured vendor_score. Empty VENDOR_SCORE_URL = off. Not a SKU."""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("decision-api.vendor_score")


def vendor_score_url() -> str:
    return (os.environ.get("VENDOR_SCORE_URL") or "").strip()


async def fetch_vendor_score(
    http: Any,
    *,
    tenant_id: str,
    entity_id: str,
    timeout_s: float = 0.05,
) -> dict[str, Any] | None:
    url = vendor_score_url()
    if not url:
        return None
    try:
        r = await http.get(
            url,
            params={"tenant_id": tenant_id, "entity_id": entity_id},
            timeout=timeout_s,
        )
        status = getattr(r, "status_code", None)
        if status is None or int(status) >= 400:
            return None
        payload = r.json() if hasattr(r, "json") else None
        if callable(payload):
            payload = await payload
        if not isinstance(payload, dict):
            return None
        score = payload.get("vendor_score", payload.get("score"))
        decision = payload.get("vendor_decision", payload.get("decision"))
        out: dict[str, Any] = {}
        if score is not None:
            out["vendor_score"] = float(score)
        if decision is not None:
            out["vendor_decision"] = str(decision)
        return out or None
    except Exception:
        log.debug("vendor_score_fail_soft", exc_info=True)
        return None
