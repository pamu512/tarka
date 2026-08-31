"""Related-object importance. Related ≠ attend. Pack bar is higher than Hunt."""

from __future__ import annotations

from typing import Any

WEAK_TYPES = frozenset({"ip", "isp"})
INSTRUMENT_TYPES = frozenset({"payment", "card"})
PACK_OUTCOME_MIN = 3
PACK_INSTRUMENT_FANOUT = 3
PACK_SESSION_FANOUT = 5

_TYPE_PRIOR = {
    "session": 40,
    "payment": 40,
    "card": 40,
    "login": 25,
    "device": 25,
    "account": 15,
    "address": 15,
    "decision": 10,
    "person": 0,
    "ip": 8,
    "isp": 8,
}


def _kind(entity_type: str) -> str:
    return str(entity_type or "").strip().lower()


def score_object_attention(
    *,
    entity_type: str,
    person_fanout: int = 0,
    review_or_deny_neighbors: int = 0,
    on_this_event: bool = False,
) -> dict[str, Any]:
    kind = _kind(entity_type)
    fanout = max(0, int(person_fanout or 0))
    outcomes = max(0, int(review_or_deny_neighbors or 0))
    reasons: list[str] = [f"type:{kind or 'custom'}"]
    importance = int(_TYPE_PRIOR.get(kind, 10))

    if outcomes:
        importance += min(outcomes * 10, 40)
        reasons.append(f"outcomes:{outcomes}")
    if fanout:
        reasons.append(f"fanout:{fanout}")
        if kind not in WEAK_TYPES:
            importance += min(fanout * 2, 20)

    if kind in WEAK_TYPES:
        importance = min(importance, 35)

    importance = max(0, min(100, importance))
    attend_pack = False
    if on_this_event and kind not in WEAK_TYPES:
        if outcomes >= PACK_OUTCOME_MIN:
            attend_pack = True
            reasons.append("pack:hot_outcomes")
        elif kind in INSTRUMENT_TYPES and fanout >= PACK_INSTRUMENT_FANOUT:
            attend_pack = True
            reasons.append("pack:shared_instrument")
        elif kind == "session" and fanout >= PACK_SESSION_FANOUT:
            attend_pack = True
            reasons.append("pack:unusual_session")

    return {
        "entity_type": entity_type or "Custom",
        "importance": importance,
        "reasons": reasons,
        "attend_hunt": True,
        "attend_pack": attend_pack,
    }


def _person_is_hot(node: dict[str, Any]) -> bool:
    risk = node.get("risk_score")
    if isinstance(risk, (int, float)) and risk >= 70:
        return True
    labels = {str(x) for x in (node.get("labels") or [])}
    if "Decision" in labels:
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        outcome = str(props.get("outcome") or props.get("decision") or "").strip().lower()
        return outcome in {"deny", "review"}
    return False


def stats_from_subgraph(seed_id: str, nodes: list[dict[str, Any]]) -> tuple[int, int]:
    """Person fan-out and hot Person/Decision neighbors around an object."""
    fanout = 0
    hot = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id") or node.get("entity_id") or "")
        if nid == seed_id:
            continue
        labels = [str(x) for x in (node.get("labels") or [])]
        if "Person" in labels:
            fanout += 1
            if _person_is_hot(node):
                hot += 1
        elif "Decision" in labels and _person_is_hot(node):
            hot += 1
    return fanout, hot


def attention_for_node(
    node: dict[str, Any],
    *,
    person_fanout: int,
    review_or_deny_neighbors: int,
    on_this_event: bool,
) -> dict[str, Any]:
    labels = [str(x) for x in (node.get("labels") or [])]
    kind = labels[0] if labels else "Custom"
    eid = str(node.get("id") or node.get("entity_id") or "")
    row = score_object_attention(
        entity_type=kind,
        person_fanout=person_fanout,
        review_or_deny_neighbors=review_or_deny_neighbors,
        on_this_event=on_this_event,
    )
    row["entity_id"] = eid
    row["entity_type"] = kind
    return row
