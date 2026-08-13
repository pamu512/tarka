from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .entity_risk_score import is_found_payload
from .graph_runtime import set_entity_risk_properties

log = logging.getLogger(__name__)


def _int_prop(payload: dict[str, Any], key: str) -> int:
    try:
        return max(0, int(payload.get(key) or 0))
    except (TypeError, ValueError):
        return 0


async def persist_entity_risk(tenant_id: str, entity_id: str, payload: dict) -> None:
    if not is_found_payload(payload):
        return
    props = {
        "risk_score": payload.get("risk_score"),
        "risk_factors": [str(x) for x in (payload.get("risk_factors") or [])],
        "risk_computed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "relation_count": _int_prop(payload, "relation_count"),
        "relation_growth_1h": _int_prop(payload, "relation_growth_1h"),
        "relation_growth_24h": _int_prop(payload, "relation_growth_24h"),
    }
    try:
        await set_entity_risk_properties(tenant_id, entity_id, props)
    except Exception:
        log.exception(
            "persist_entity_risk SET failed tenant=%s entity=%s",
            tenant_id,
            entity_id,
        )
