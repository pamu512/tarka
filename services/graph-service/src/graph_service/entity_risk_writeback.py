from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from .algorithms import compute_entity_risk
from .entity_risk_score import is_found_payload, p90_degree
from .graph_runtime import (
    list_one_hop_ids,
    scan_tenant_entity_ids,
    set_entity_risk_properties,
    upsert_graph_risk_stats,
)

log = logging.getLogger(__name__)

MUTATION_REFRESH_CAP = 50
TOP_LIMIT_DEFAULT = 50
TOP_LIMIT_MAX = 200
REFRESH_LIMIT_DEFAULT = 5000
REFRESH_LIMIT_MAX = 20000


class EntityRiskNotFound(LookupError):
    pass


def clamp_top_limit(limit: int) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = TOP_LIMIT_DEFAULT
    return max(1, min(n, TOP_LIMIT_MAX))


def clamp_refresh_limit(limit: int) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = REFRESH_LIMIT_DEFAULT
    return max(1, min(n, REFRESH_LIMIT_MAX))


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


async def refresh_entity(
    tenant_id: str,
    entity_id: str,
    *,
    compute_fn=None,
) -> dict[str, Any]:
    compute = compute_fn or compute_entity_risk
    payload = await compute(tenant_id, entity_id)
    if not is_found_payload(payload):
        raise EntityRiskNotFound(entity_id)
    await persist_entity_risk(tenant_id, entity_id, payload)
    return {"updated": 1, "skipped": 0, "truncated": False}


async def refresh_tenant(tenant_id: str, limit: int = REFRESH_LIMIT_DEFAULT) -> dict[str, Any]:
    limit = clamp_refresh_limit(limit)
    ids, truncated = await scan_tenant_entity_ids(tenant_id, limit)
    updated = 0
    skipped = 0
    by_label: dict[str, list[int]] = {}
    for eid in ids:
        try:
            payload = await compute_entity_risk(tenant_id, eid)
        except Exception:
            log.exception("tenant risk refresh compute failed tenant=%s entity=%s", tenant_id, eid)
            skipped += 1
            continue
        if not is_found_payload(payload):
            skipped += 1
            continue
        await persist_entity_risk(tenant_id, eid, payload)
        updated += 1
        label = str(payload.get("primary_label") or "").strip()
        if label:
            by_label.setdefault(label, []).append(_int_prop(payload, "relation_count"))
    p90_map: dict[str, int] = {}
    for label, values in by_label.items():
        p90 = p90_degree(values)
        if p90 is not None:
            p90_map[label] = p90
    await upsert_graph_risk_stats(
        tenant_id,
        p90_map,
        datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    return {"updated": updated, "skipped": skipped, "truncated": bool(truncated)}
