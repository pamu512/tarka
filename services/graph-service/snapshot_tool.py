"""
JanusGraph **2-hop neighborhood snapshot** for a ``User`` anchor (``user_id``).

Runs Gremlin against the same vertex/edge schema as :mod:`cache_warmer` /
``orchestrator.graph.client`` (labels ``User``, ``Device``, ``IP``, …).

Output: JSON-serializable tree
``{ anchor, one_hop: [ { vertex, edge_from_anchor, two_hop: [...] } ] }`` suitable for
investigation / evidence bundles.

Env (Gremlin): ``GREMLIN_REMOTE_URL`` (default ``ws://127.0.0.1:8182/gremlin``),
``GREMLIN_TRAVERSAL_SOURCE`` (``g``).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Same ontology as ``cache_warmer.py`` / orchestrator Janus ingest.
LABEL_USER = "User"
LABEL_DEVICE = "Device"
LABEL_IP = "IP"
LABEL_CARD = "Card"
LABEL_EMAIL = "Email"
LABEL_ADDRESS = "Address"
LABEL_ORDER = "Order"
LABEL_PASSPORT = "Passport"
LABEL_LISTING = "Listing"


def _here() -> Path:
    return Path(__file__).resolve().parent


def _ensure_graph_service_path() -> None:
    p = str(_here())
    if p not in sys.path:
        sys.path.insert(0, p)


def _gremlin_T() -> Any:  # noqa: N802
    from gremlin_python.process.traversal import T

    return T


def element_map_to_public(em: dict[Any, Any]) -> dict[str, Any]:
    """Turn a Gremlin ``elementMap()`` row into JSON-safe ``{id, label, properties}``."""
    T = _gremlin_T()
    vid = em.get(T.id)
    lbl = em.get(T.label)
    props: dict[str, Any] = {}
    for k, v in em.items():
        if k in (T.id, T.label):
            continue
        props[str(k)] = _jsonify_gremlin_value(v)
    return {
        "id": str(vid) if vid is not None else "",
        "label": str(lbl) if lbl is not None else "",
        "properties": props,
    }


def edge_element_map_to_public(em: dict[Any, Any]) -> dict[str, Any]:
    """JSON-safe edge description from ``bothE().elementMap()``."""
    T = _gremlin_T()
    eid = em.get(T.id)
    lbl = em.get(T.label)
    props: dict[str, Any] = {}
    for k, v in em.items():
        if k in (T.id, T.label):
            continue
        props[str(k)] = _jsonify_gremlin_value(v)
    return {
        "id": str(eid) if eid is not None else "",
        "label": str(lbl) if lbl is not None else "",
        "properties": props,
    }


def _jsonify_gremlin_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    if isinstance(v, (list, tuple)):
        return [_jsonify_gremlin_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonify_gremlin_value(val) for k, val in v.items()}
    return str(v)


def build_neighborhood_tree_from_gremlin_maps(
    *,
    user_id: str,
    anchor_em: dict[Any, Any] | None,
    one_hop_edge_vertex_rows: list[dict[str, Any]],
    two_hop_fetcher: Any,
) -> dict[str, Any]:
    """
    Pure assembly of the snapshot dict from Gremlin-shaped rows.

    ``one_hop_edge_vertex_rows``: each item is ``{"edge": <edge elementMap>, "neighbor": <vertex elementMap>}``.
    ``two_hop_fetcher(neighbor_tid: Any) -> list[dict]`` returns rows ``{"edge": edgeEm, "vertex": vEm}`` for
    vertices reachable in one undirected step from the neighbor excluding the anchor vertex id.
    """
    uid = (user_id or "").strip()
    out: dict[str, Any] = {
        "schema": "janusgraph.neighborhood_snapshot.v1",
        "user_id": uid,
        "found": False,
        "anchor": None,
        "one_hop": [],
    }
    if not uid or anchor_em is None:
        return out
    T = _gremlin_T()
    anchor_tid = anchor_em.get(T.id)
    out["found"] = True
    out["anchor"] = element_map_to_public(anchor_em)

    for row in one_hop_edge_vertex_rows:
        e_map = row.get("edge")
        n_map = row.get("neighbor")
        if not isinstance(e_map, dict) or not isinstance(n_map, dict):
            continue
        nid = n_map.get(T.id)
        two_rows = two_hop_fetcher(nid, anchor_tid)
        two_hop_out: list[dict[str, Any]] = []
        for tr in two_rows:
            te = tr.get("edge")
            tv = tr.get("vertex")
            if isinstance(te, dict) and isinstance(tv, dict):
                two_hop_out.append(
                    {
                        "depth": 2,
                        "vertex": element_map_to_public(tv),
                        "edge_from_one_hop": edge_element_map_to_public(te),
                    }
                )
        out["one_hop"].append(
            {
                "depth": 1,
                "vertex": element_map_to_public(n_map),
                "edge_from_anchor": edge_element_map_to_public(e_map),
                "two_hop": two_hop_out,
            }
        )
    return out


def fetch_two_hop_neighborhood_snapshot_sync(
    g: Any,
    user_id: str,
    *,
    max_one_hop_branches: int = 200,
    max_two_hop_per_branch: int = 100,
) -> dict[str, Any]:
    """
    Query JanusGraph: anchor ``User`` by ``user_id``, 1-hop ``bothE``/``otherV``, then per neighbor
    one more ``both()`` excluding the anchor (2-hop branch relative to anchor).
    """
    from gremlin_python.process.graph_traversal import __

    T = _gremlin_T()
    uid = (user_id or "").strip()
    if not uid:
        return build_neighborhood_tree_from_gremlin_maps(
            user_id=uid,
            anchor_em=None,
            one_hop_edge_vertex_rows=[],
            two_hop_fetcher=lambda _n, _a: [],
        )

    anchor_list = g.V().has(LABEL_USER, "user_id", uid).limit(1).elementMap().toList()
    if not anchor_list:
        return build_neighborhood_tree_from_gremlin_maps(
            user_id=uid,
            anchor_em=None,
            one_hop_edge_vertex_rows=[],
            two_hop_fetcher=lambda _n, _a: [],
        )
    anchor_em = anchor_list[0]
    anchor_tid = anchor_em[T.id]

    one_hop_rows_raw = (
        g.V()
        .hasId(anchor_tid)
        .bothE()
        .limit(max_one_hop_branches)
        .project("edge", "neighbor")
        .by(__.elementMap())
        .by(__.otherV().elementMap())
        .toList()
    )

    one_hop_rows: list[dict[str, Any]] = []
    seen_neighbor: set[Any] = set()
    for row in one_hop_rows_raw:
        if not isinstance(row, dict):
            continue
        n_map = row.get("neighbor")
        if not isinstance(n_map, dict):
            continue
        nid = n_map.get(T.id)
        if nid in seen_neighbor:
            continue
        seen_neighbor.add(nid)
        one_hop_rows.append({"edge": row.get("edge"), "neighbor": n_map})

    def _two_hop(nid: Any, anchor_id: Any) -> list[dict[str, Any]]:
        try:
            raw_v = (
                g.V().hasId(nid).both().dedup().limit(max_two_hop_per_branch).elementMap().toList()
            )
            verts = [v for v in raw_v if isinstance(v, dict) and v.get(T.id) != anchor_id][
                :max_two_hop_per_branch
            ]
        except Exception:
            logger.exception("snapshot_two_hop_branch_failed neighbor_id=%s", nid)
            return []
        out2: list[dict[str, Any]] = []
        for tv in verts:
            if not isinstance(tv, dict):
                continue
            v_tid = tv.get(T.id)
            e_map: dict[Any, Any] = {}
            try:
                el = (
                    g.V()
                    .hasId(nid)
                    .bothE()
                    .where(__.otherV().hasId(v_tid))
                    .limit(1)
                    .elementMap()
                    .toList()
                )
                if el:
                    e_map = el[0] if isinstance(el[0], dict) else {}
            except Exception:
                logger.debug("snapshot_two_hop_edge_lookup_failed", exc_info=True)
            out2.append({"edge": e_map, "vertex": tv})
        return out2

    return build_neighborhood_tree_from_gremlin_maps(
        user_id=uid,
        anchor_em=anchor_em,
        one_hop_edge_vertex_rows=one_hop_rows,
        two_hop_fetcher=_two_hop,
    )


async def fetch_two_hop_neighborhood_snapshot(
    user_id: str, *, g: Any | None = None
) -> dict[str, Any]:
    """Async wrapper; builds ``g`` from env when omitted (closes connection when created here)."""
    import asyncio

    if g is not None:
        return await asyncio.to_thread(fetch_two_hop_neighborhood_snapshot_sync, g, user_id)

    _ensure_graph_service_path()
    from cache_warmer import traversal_source_from_env

    g2, conn = traversal_source_from_env()
    try:
        return await asyncio.to_thread(fetch_two_hop_neighborhood_snapshot_sync, g2, user_id)
    finally:
        try:
            conn.close()
        except Exception:
            logger.debug("snapshot_gremlin_close_failed", exc_info=True)


def snapshot_json(user_id: str, *, g: Any | None = None, indent: int | None = 2) -> str:
    """Return pretty-printed JSON (sync path uses injected ``g`` only)."""
    if g is None:
        raise ValueError(
            "Pass traversal source g=... or use fetch_two_hop_neighborhood_snapshot async"
        )
    tree = fetch_two_hop_neighborhood_snapshot_sync(g, user_id)
    return json.dumps(tree, indent=indent)


def main() -> None:
    """CLI: ``python snapshot_tool.py <user_id>`` (requires Gremlin env)."""
    import asyncio

    logging.basicConfig(level=logging.INFO)
    uid = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not uid:
        print("usage: python snapshot_tool.py <user_id>", file=sys.stderr)
        sys.exit(2)
    tree = asyncio.run(fetch_two_hop_neighborhood_snapshot(uid))
    print(json.dumps(tree, indent=2))


if __name__ == "__main__":
    main()
