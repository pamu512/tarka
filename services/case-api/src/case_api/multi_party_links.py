"""Multi-party collusion links via graph risk_propagation + case entity join."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Case

_ROLE_MAP = {
    "buyer": ("buyer", "consumer", "diner", "customer", "user"),
    "seller": ("seller", "merchant", "shop", "restaurant"),
    "courier": ("courier", "driver", "partner", "rider", "dasher"),
}

_REASON_LABEL_PREFIX = "disposition:"


def map_labels_to_roles(labels: list[str]) -> list[str]:
    roles: list[str] = []
    lower = {str(x).lower() for x in labels}
    for role, keys in _ROLE_MAP.items():
        if lower & set(keys):
            roles.append(role)
    return roles or ["unknown"]


def _shared_signals_from_rel_types(rel_types: list[Any] | None) -> list[str]:
    if not rel_types:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for rt in rel_types:
        sig = str(rt).strip().lower()
        if sig and sig not in seen:
            seen.add(sig)
            out.append(sig)
    return out


def _disposition_from_labels(labels: list[Any] | None) -> str | None:
    if not labels:
        return None
    for lab in labels:
        s = str(lab)
        if s.startswith(_REASON_LABEL_PREFIX):
            reason = s[len(_REASON_LABEL_PREFIX) :].strip()
            return reason or None
    return None


def _case_link_row(case: Case) -> dict[str, Any]:
    row: dict[str, Any] = {
        "case_id": str(case.id),
        "status": case.status,
    }
    disp = _disposition_from_labels(case.labels)
    if disp:
        row["disposition_reason"] = disp
    return row


async def build_multi_party_links(
    session: AsyncSession,
    case: Case,
    *,
    http: httpx.AsyncClient,
    depth: int = 3,
) -> dict[str, Any]:
    """Build multi-party link payload for a case anchor entity.

    Calls graph ``/v1/analytics/risk-propagation`` (same backend as case graph routes).
    Fail-soft: HTTP 200 callers receive ``degraded: true`` when graph is unreachable.
    """
    out: dict[str, Any] = {
        "case_id": str(case.id),
        "entity_id": case.entity_id,
        "tenant_id": case.tenant_id,
        "links": [],
    }

    base = (settings.graph_service_url or "").strip().rstrip("/")
    if not base:
        out["degraded"] = True
        out["degraded_reason"] = "graph_unavailable"
        return out

    try:
        r = await http.get(
            f"{base}/v1/analytics/risk-propagation",
            params={
                "tenant_id": case.tenant_id,
                "entity_id": case.entity_id,
                "depth": depth,
            },
            timeout=8.0,
        )
        r.raise_for_status()
        graph_data = r.json()
    except Exception:
        out["degraded"] = True
        out["degraded_reason"] = "graph_unavailable"
        return out

    entities = graph_data.get("entities")
    if not isinstance(entities, list):
        out["degraded"] = True
        out["degraded_reason"] = "graph_unavailable"
        return out

    neighbor_ids: list[str] = []
    entity_rows: list[dict[str, Any]] = []
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        eid = ent.get("entity_id")
        if not eid or str(eid) == case.entity_id:
            continue
        neighbor_ids.append(str(eid))
        entity_rows.append(ent)

    cases_by_entity: dict[str, list[Case]] = {}
    if neighbor_ids:
        result = await session.execute(
            select(Case).where(
                Case.tenant_id == case.tenant_id,
                Case.entity_id.in_(neighbor_ids),
            )
        )
        for row in result.scalars().all():
            cases_by_entity.setdefault(row.entity_id, []).append(row)

    links: list[dict[str, Any]] = []
    for ent in entity_rows:
        eid = str(ent["entity_id"])
        raw_labels = ent.get("entity_labels") or []
        labels = raw_labels if isinstance(raw_labels, list) else [raw_labels]
        links.append(
            {
                "entity_id": eid,
                "roles": map_labels_to_roles(labels),
                "distance": int(ent.get("distance") or 0),
                "propagated_risk_score": float(ent.get("propagated_risk_score") or 0.0),
                "path_description": str(ent.get("path_description") or ""),
                "shared_signals": _shared_signals_from_rel_types(ent.get("rel_types")),
                "cases": [_case_link_row(c) for c in cases_by_entity.get(eid, [])],
            }
        )

    links.sort(key=lambda x: (x["distance"], -x["propagated_risk_score"]))
    out["links"] = links
    return out
