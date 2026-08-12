"""Merge partner_graph_hints (OCR/device) into party_graph for ring_score.

Best decision: reuse existing writeback schema; do not invent LIVE OCR claims.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def merge_partner_hints_into_party_graph(
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return metadata copy with party_graph enriched from partner_graph_hints.

    Supports:
    - partner_graph_hints.vertices/edges (Place / SEEN_AT / Device style)
    - partner_graph_hints.ocr_device_clusters[] → device bridges
    - metadata.device_cluster_ids[] already handled elsewhere; also merged here
      when person ids are present on the graph.
    """
    if not isinstance(metadata, dict):
        return None
    hints = metadata.get("partner_graph_hints") or metadata.get("ocr_graph_hints")
    clusters = metadata.get("device_cluster_ids")
    if not isinstance(hints, dict) and not clusters:
        return metadata

    out = deepcopy(metadata)
    g = out.get("party_graph")
    if not isinstance(g, dict):
        g = {"nodes": [], "edges": []}
        out["party_graph"] = g
    nodes = list(g.get("nodes") or []) if isinstance(g.get("nodes"), list) else []
    edges = list(g.get("edges") or []) if isinstance(g.get("edges"), list) else []
    by_id = {str(n.get("id")): n for n in nodes if isinstance(n, dict) and n.get("id")}

    def _ensure_node(nid: str, role: str) -> None:
        if nid in by_id:
            return
        node = {"id": nid, "role": role}
        nodes.append(node)
        by_id[nid] = node

    if isinstance(hints, dict):
        for v in hints.get("vertices") or []:
            if not isinstance(v, dict):
                continue
            vid = str(v.get("id") or "").strip()
            if not vid:
                continue
            label = str(v.get("label") or "").strip().lower()
            role = (
                "place"
                if label == "place"
                else ("device" if label == "device" else str(v.get("role") or "device"))
            )
            _ensure_node(vid[:128], role[:64])

        for e in hints.get("edges") or []:
            if not isinstance(e, dict):
                continue
            et = str(e.get("type") or "").strip().upper() or "RELATED"
            src = e.get("src") or (e.get("from") or {})
            dst = e.get("dst") or (e.get("to") or {})
            if isinstance(src, dict):
                sid = str(src.get("id") or "").strip()
            else:
                sid = str(src or "").strip()
            if isinstance(dst, dict):
                did = str(dst.get("id") or "").strip()
            else:
                did = str(dst or "").strip()
            if not sid or not did:
                continue
            if sid not in by_id:
                _ensure_node(sid[:128], "device" if et == "USES_DEVICE" else "place")
            if did not in by_id:
                _ensure_node(did[:128], "place" if et == "SEEN_AT" else "device")
            edges.append(
                {
                    "src": sid[:128],
                    "dst": did[:128],
                    "type": et,
                    "source": "partner_hint",
                }
            )

        # OCR device clusters: {cluster_id, entity_ids:[{id, role}]}
        for cl in hints.get("ocr_device_clusters") or []:
            if not isinstance(cl, dict):
                continue
            cid = str(cl.get("cluster_id") or cl.get("id") or "").strip()
            if not cid:
                continue
            _ensure_node(f"ocrdev:{cid}"[:128], "device")
            for ent in cl.get("entity_ids") or cl.get("members") or []:
                if isinstance(ent, dict):
                    eid = str(ent.get("id") or "").strip()
                    role = str(ent.get("role") or "buyer").strip().lower() or "buyer"
                else:
                    eid = str(ent or "").strip()
                    role = "buyer"
                if not eid:
                    continue
                _ensure_node(eid[:128], role[:64])
                edges.append(
                    {
                        "src": eid[:128],
                        "dst": f"ocrdev:{cid}"[:128],
                        "type": "USES_DEVICE",
                        "source": "ocr_device_cluster",
                    }
                )

    g["nodes"] = nodes
    g["edges"] = edges
    g["hints_merged"] = True
    out["party_graph"] = g
    return out
