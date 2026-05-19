"""Knowledge-drop enrichment: graph linkage + lifecycle case conflicts for extracted IDs."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orchestrator.analytics.provider import AnalyticsProvider
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.graph.client import GraphClient
from orchestrator.models.cases import CaseORM, CaseStatus

logger = logging.getLogger(__name__)

_ACTIVE_INVESTIGATION_STATUSES = frozenset(
    {
        CaseStatus.OPEN.value,
        CaseStatus.UNDER_REVIEW.value,
        CaseStatus.PENDING_ACTION.value,
    },
)


def classify_detected_id(detected_id: str) -> str:
    """Coarse token class for analyst-facing copy (not security-critical)."""
    s = (detected_id or "").strip()
    if not s:
        return "unknown"
    try:
        UUID(s)
        return "uuid"
    except ValueError:
        pass
    up = s.upper()
    if re.match(r"^(?:ORD|ORDER)[-_#]?", up):
        return "order"
    if re.search(r"(?i)passport", s) or re.match(r"^(?:PP|PPT)[-_#]?", up):
        return "passport"
    if re.match(r"^(?:TXN|TX|TRX)[-_#]?", up):
        return "txn"
    if re.match(r"(?i)^cust[_-]\d+", s):
        return "customer"
    return "token"


def _short_label(s: str, *, max_len: int = 22) -> str:
    t = (s or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def build_mini_graph(
    *,
    detected_id: str,
    id_kind: str,
    user_ids: list[str],
    n_investigations: int,
    found_in_graph: bool,
) -> dict[str, Any]:
    """Compact nodes/edges for a side-panel SVG (deterministic layout hints)."""
    anchor = "anchor"
    nodes: list[dict[str, str]] = [
        {
            "id": anchor,
            "label": _short_label(detected_id),
            "kind": "id",
            "subkind": id_kind,
        },
    ]
    edges: list[dict[str, str]] = []

    cap = 6
    for i, uid in enumerate(user_ids[:cap]):
        nid = f"u{i}"
        nodes.append({"id": nid, "label": _short_label(uid, max_len=18), "kind": "user"})
        edges.append({"from": anchor, "to": nid, "rel": "linked"})

    if found_in_graph and n_investigations > 0 and not user_ids:
        nodes.append(
            {
                "id": "inv",
                "label": f"{n_investigations} active",
                "kind": "investigations",
            },
        )
        edges.append({"from": anchor, "to": "inv", "rel": "cases"})

    return {"nodes": nodes, "edges": edges}


def _safe_entity_ids(*parts: str | None) -> set[str]:
    out: set[str] = set()
    for p in parts:
        if not p:
            continue
        s = str(p).strip()
        if not s:
            continue
        try:
            UUID(s)
        except ValueError:
            continue
        out.add(s)
    return out


async def _lifecycle_snapshot(
    session: AsyncSession, entity_ids: set[str]
) -> tuple[int, bool, list[str]]:
    if not entity_ids:
        return 0, False, []
    stmt = select(CaseORM).where(CaseORM.entity_id.in_(entity_ids))
    rows = (await session.execute(stmt)).scalars().all()
    active = [r for r in rows if r.status in _ACTIVE_INVESTIGATION_STATUSES]
    pending = [r for r in rows if r.status == CaseStatus.PENDING_ACTION.value]
    return len(active), bool(pending), [str(r.case_id) for r in pending]


async def resolve_knowledge_row(
    detected_id: str,
    graph_client: GraphClient,
    session: AsyncSession | None,
    analytics: AnalyticsProvider | None = None,
) -> dict[str, Any]:
    raw, two_hop = await asyncio.gather(
        graph_client.knowledge_linked_users(detected_id),
        graph_client.two_hop_neighbor_network(detected_id),
    )
    id_kind = classify_detected_id(detected_id)
    users = [str(u) for u in (raw.get("linked_user_ids") or []) if u is not None and str(u).strip()]
    tids_raw = raw.get("related_entity_ids") or []
    tids = [str(t) for t in tids_raw if t is not None and str(t).strip()]

    entity_ids = _safe_entity_ids(detected_id, *tids)

    active_n = 0
    pending_conflict = False
    pending_ids: list[str] = []
    if session is not None and entity_ids:
        active_n, pending_conflict, pending_ids = await _lifecycle_snapshot(session, entity_ids)

    mini = build_mini_graph(
        detected_id=detected_id,
        id_kind=id_kind,
        user_ids=users,
        n_investigations=active_n,
        found_in_graph=bool(raw.get("found")),
    )

    duck_cluster: dict[str, Any] = {}
    if analytics is not None and bool(two_hop.get("found")):
        try:
            duck_cluster = await asyncio.to_thread(
                analytics.cluster_spend_velocity_for_network,
                transaction_entity_ids=list(two_hop.get("network_transaction_ids") or ()),
                network_user_ids=list(two_hop.get("network_user_ids") or ()),
                days=30,
            )
        except Exception:
            logger.exception("knowledge_drop_duck_cluster_failed detected_id=%s", detected_id)
            duck_cluster = {"error": "duck_cluster_failed"}

    return {
        "detected_id": detected_id,
        "id_kind": id_kind,
        "found_in_graph": bool(raw.get("found")),
        "match_kind": raw.get("match_kind"),
        "graph_backend": raw.get("backend"),
        "linked_user_ids": users,
        "active_investigation_count": active_n,
        "pending_action_conflict": pending_conflict,
        "pending_action_case_ids": pending_ids,
        "mini_graph": mini,
        "two_hop_network": two_hop,
        "duck_cluster_velocity": duck_cluster,
    }


async def knowledge_bundle_for_detected_ids(
    detected_ids: list[str],
    *,
    graph_client: GraphClient,
    session: AsyncSession | None,
    analytics: AnalyticsProvider | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for did in detected_ids:
        try:
            out.append(await resolve_knowledge_row(did, graph_client, session, analytics=analytics))
        except Exception:
            logger.exception("knowledge_drop_resolve_failed detected_id=%s", did)
            out.append(
                {
                    "detected_id": did,
                    "id_kind": classify_detected_id(did),
                    "found_in_graph": False,
                    "match_kind": None,
                    "graph_backend": "error",
                    "linked_user_ids": [],
                    "active_investigation_count": 0,
                    "pending_action_conflict": False,
                    "pending_action_case_ids": [],
                    "mini_graph": {"nodes": [], "edges": []},
                    "two_hop_network": {"found": False, "anchor_user_id": did, "backend": "error"},
                    "duck_cluster_velocity": {},
                },
            )
    return out
