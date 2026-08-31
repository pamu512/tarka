"""Deny-by-default markings on Decision vertices (Hunt reads)."""

from __future__ import annotations

from typing import Any

DEFAULT_DESK = "desk"


def parse_caller_markings(header: str | None) -> frozenset[str]:
    if header is None:
        return frozenset()
    return frozenset(part.strip().lower() for part in str(header).split(",") if part.strip())


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("id") or node.get("entity_id") or node.get("external_id") or "")


def _is_decision(node: dict[str, Any]) -> bool:
    if str(node.get("entity_type") or "") == "Decision":
        return True
    return "Decision" in [str(x) for x in (node.get("labels") or [])]


def _node_markings(node: dict[str, Any]) -> set[str]:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    raw = props.get("markings")
    if isinstance(raw, str):
        return {raw.strip().lower()} if raw.strip() else set()
    if isinstance(raw, list):
        return {str(x).strip().lower() for x in raw if str(x).strip()}
    return set()


def decision_visible(node: dict[str, Any], caller: frozenset[str]) -> bool:
    if not _is_decision(node):
        return True
    marks = _node_markings(node)
    if not marks or not caller:
        return False
    return bool(marks & caller)


def filter_subgraph_for_read(data: dict[str, Any], caller: frozenset[str]) -> dict[str, Any]:
    nodes = [
        n for n in (data.get("nodes") or []) if isinstance(n, dict) and decision_visible(n, caller)
    ]
    keep = {_node_id(n) for n in nodes}
    edges = []
    for edge in data.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("from_id") or edge.get("from") or "")
        dst = str(edge.get("to_id") or edge.get("to") or "")
        if src in keep and dst in keep:
            edges.append(edge)
    out = dict(data)
    out["nodes"] = nodes
    out["edges"] = edges
    return out
