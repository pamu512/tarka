"""Post-AGE Hunt net: receipt lookback + type allow-list. Rank/cap stay on the client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

RECEIPT_LABELS = frozenset({"Login", "Session", "Decision"})
MAX_LOOKBACK_DAYS = 2555


def clamp_lookback_days(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return None
    if days < 1:
        return None
    return min(days, MAX_LOOKBACK_DAYS)


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("id") or node.get("entity_id") or node.get("external_id") or "")


def _primary_label(node: dict[str, Any]) -> str:
    labels = node.get("labels") or []
    if labels:
        return str(labels[0])
    return str(node.get("entity_type") or "")


def _hop_time(node: dict[str, Any]) -> datetime | None:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    for key in ("created_at", "observed_at", "last_seen", "updated_at"):
        raw = props.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
    return None


def apply_hunt_net(
    data: dict[str, Any],
    *,
    seed_id: str,
    lookback_days: int | None,
    types: list[str] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
    edges = [e for e in (data.get("edges") or []) if isinstance(e, dict)]
    allow = {t.strip() for t in (types or []) if t and t.strip()} or None
    since = None
    if lookback_days is not None:
        clock = now or datetime.now(UTC)
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=UTC)
        since = clock - timedelta(days=lookback_days)
    drop: set[str] = set()
    for node in nodes:
        nid = _node_id(node)
        if not nid or nid == seed_id:
            continue
        label = _primary_label(node)
        if allow is not None and label not in allow:
            drop.add(nid)
            continue
        if since is None or label not in RECEIPT_LABELS:
            continue
        ts = _hop_time(node)
        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts < since:
                drop.add(nid)
    kept = [n for n in nodes if _node_id(n) not in drop]
    ids = {_node_id(n) for n in kept}
    kept_edges = []
    for edge in edges:
        src = str(edge.get("from_id") or edge.get("from") or "")
        dst = str(edge.get("to_id") or edge.get("to") or "")
        if src in ids and dst in ids:
            kept_edges.append(edge)
    out = dict(data)
    out["nodes"] = kept
    out["edges"] = kept_edges
    return out
