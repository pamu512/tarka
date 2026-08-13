from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from .algorithms import compute_entity_risk
from .entity_risk_score import is_found_payload
from .graph_runtime import list_one_hop_ids, set_entity_risk_properties

log = logging.getLogger(__name__)

MUTATION_REFRESH_CAP = 50


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


async def refresh_touched_and_neighbors(tenant_id: str, entity_ids: Sequence[str]) -> None:
    try:
        ordered: list[str] = []
        seen: set[str] = set()
        for eid in entity_ids:
            if not eid or eid in seen:
                continue
            seen.add(eid)
            ordered.append(eid)
        for eid in list(ordered):
            try:
                hops = await list_one_hop_ids(tenant_id, eid)
            except Exception:
                log.exception(
                    "list_one_hop_ids failed tenant=%s entity=%s",
                    tenant_id,
                    eid,
                )
                hops = []
            for hid in hops:
                if not hid or hid in seen:
                    continue
                seen.add(hid)
                ordered.append(hid)
        for eid in ordered[:MUTATION_REFRESH_CAP]:
            try:
                payload = await compute_entity_risk(tenant_id, eid)
                await persist_entity_risk(tenant_id, eid, payload)
            except Exception:
                log.exception(
                    "mutation risk refresh failed tenant=%s entity=%s",
                    tenant_id,
                    eid,
                )
    except Exception:
        log.exception("refresh_touched_and_neighbors failed tenant=%s", tenant_id)
