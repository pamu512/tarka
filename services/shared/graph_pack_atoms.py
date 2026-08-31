"""Versioned graph pack atoms (tarka.graph_pack_atoms/v1).

JSON packs predicate on the as-of hop already on the request — named edges,
multi-id, sibling FLAG/y_label. Empty GRAPH_SERVICE_URL / graph:missing is
missing (false). Unsigned etype or role is refused or missed; never RELATED.
Replay reads a stored snapshot. Does not invent neighbors or call the graph.
"""

from __future__ import annotations

import re
from typing import Any

from graph_contract import (
    CORE_ETYPES,
    UnsignedGraphToken,
    consume_graph_answers,
    empty_graph_answers,
    pack_why_from_graph_answers,
    registered_etypes,
    require_role,
)

SCHEMA_ID = "tarka.graph_pack_atoms/v1"
HOP_FEATURE_KEY = "_graph_hop_v1"

# Evaluate-facing named etypes (plus graph_contract CORE + tenant extras).
PACK_HOP_ETYPES = frozenset(
    {
        "USES_DEVICE",
        "HAS_PHONE",
        "SEEN_FROM_IP",
        "SEEN_AT",
        "PAYS_WITH",
        "REDEEMS",
        "ON_ORDER",
        "PARTY_WITH",
    }
)

# Hunt / upsert write names → pack atom names. Same fact, one hop view.
ETYPE_WRITE_TO_PACK = {
    "USED_DEVICE": "USES_DEVICE",
    "USED": "USES_DEVICE",
    "USED_IP": "SEEN_FROM_IP",
    "MADE_PAYMENT": "PAYS_WITH",
}

GRAPH_V1_ATOMS = frozenset({"has_etype", "has_multi_id", "sibling_prior_flag"})
_SAFE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_MISSING = frozenset({"graph:missing", "graph:unavailable", "graph:empty"})
_POSITIVE_FLAGS = frozenset({"1", "true", "flag", "flagged", "fraud", "block", "blocked"})


def _norm_etype(raw: str) -> str:
    return str(raw or "").strip().upper().replace(" ", "_").replace("-", "_")


def canonical_pack_etype(raw: str) -> str:
    token = _norm_etype(raw)
    return ETYPE_WRITE_TO_PACK.get(token, token)


def signed_pack_etypes(tenant_id: str) -> frozenset[str]:
    return frozenset(PACK_HOP_ETYPES | CORE_ETYPES | registered_etypes(tenant_id))


def require_pack_etype(tenant_id: str, etype: str) -> str:
    token = _norm_etype(etype)
    if not token or not _SAFE.fullmatch(token) or token not in signed_pack_etypes(tenant_id):
        raise UnsignedGraphToken("etype", etype, tenant_id=tenant_id)
    return token


def refuse_pack_etype_token(etype: str) -> str:
    """Parse-time refuse: RELATED / malformed. Tenant extras are checked at eval."""
    token = _norm_etype(etype)
    if not token or not _SAFE.fullmatch(token) or token == "RELATED":
        raise UnsignedGraphToken("etype", etype)
    return token


def _positive_flag(raw: Any) -> bool:
    if raw is True:
        return True
    if raw is False or raw is None:
        return False
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return raw == 1
    token = str(raw).strip().lower()
    return token in _POSITIVE_FLAGS


def _node_id(node: dict[str, Any]) -> str:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    return str(
        node.get("id")
        or node.get("external_id")
        or node.get("entity_id")
        or props.get("external_id")
        or props.get("id")
        or ""
    ).strip()


def _iter_nodes(raw: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in ("vertices", "nodes"):
        bag = raw.get(key)
        if isinstance(bag, list):
            out.extend(x for x in bag if isinstance(x, dict))
    return out


def _node_flag_value(node: dict[str, Any]) -> Any:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    for src in (node, props):
        for key in ("y_label", "FLAG", "flag"):
            if key in src and src[key] not in (None, ""):
                return src[key]
        tags = src.get("tags")
        if isinstance(tags, list) and any(
            str(t).strip().lower() in _POSITIVE_FLAGS | {"flag"} for t in tags
        ):
            return "FLAG"
    return None


def sibling_flags_from_payload(
    raw: dict[str, Any] | None,
    *,
    multi_id_user_ids: list[str],
    subject_id: str = "",
) -> dict[str, Any]:
    """Lift sibling FLAG / y_label already on the hop. Does not look up a store."""
    if not isinstance(raw, dict):
        return {}
    sid = str(subject_id or "").strip()
    flags: dict[str, Any] = {}

    for key in ("sibling_y_labels", "y_labels"):
        bag = raw.get(key)
        if not isinstance(bag, dict):
            continue
        for uid, val in bag.items():
            token = str(uid).strip()
            if token and token != sid and _positive_flag(val):
                flags[token] = val

    flagged = raw.get("flagged_user_ids")
    if isinstance(flagged, list):
        for uid in flagged:
            token = str(uid).strip()
            if token and token != sid:
                flags[token] = "FLAG"

    for node in _iter_nodes(raw):
        nid = _node_id(node)
        if not nid or nid == sid:
            continue
        val = _node_flag_value(node)
        if _positive_flag(val):
            flags[nid] = val

    multi = {str(x).strip() for x in multi_id_user_ids if str(x).strip()}
    if multi:
        return {uid: flags[uid] for uid in multi if uid in flags}
    # ponytail: empty multi-id still lifts hop-local FLAG/y_label so sibling_prior_flag can fire alone.
    return flags


def _is_missing(
    *,
    graph_url: str,
    degrade_tags: list[str] | None,
) -> bool:
    if not (graph_url or "").strip():
        return True
    tags = degrade_tags or []
    return "graph:missing" in tags


def _blank_hop(*, status: str, tenant_id: str, subject_id: str) -> dict[str, Any]:
    empty = empty_graph_answers()
    return {
        "schema_id": SCHEMA_ID,
        "status": status,
        "tenant_id": str(tenant_id or ""),
        "subject_id": str(subject_id or ""),
        "named_edges": list(empty["named_edges"]),
        "multi_id_user_ids": list(empty["multi_id_user_ids"]),
        "roles": list(empty["roles"]),
        "sibling_flags": {},
        "signed_etypes": sorted(signed_pack_etypes(tenant_id)),
        "invented_edges": False,
    }


def hop_view_from_graph_meta(
    graph_meta: dict[str, Any] | None,
    *,
    graph_url: str,
    degrade_tags: list[str] | None = None,
    tenant_id: str = "",
    subject_id: str = "",
) -> dict[str, Any]:
    if _is_missing(graph_url=graph_url, degrade_tags=degrade_tags):
        return _blank_hop(status="graph:missing", tenant_id=tenant_id, subject_id=subject_id)
    if not isinstance(graph_meta, dict):
        return _blank_hop(status="graph:empty", tenant_id=tenant_id, subject_id=subject_id)
    meta_status = str(graph_meta.get("status") or "")
    if meta_status in _MISSING:
        return _blank_hop(status=meta_status, tenant_id=tenant_id, subject_id=subject_id)
    answers = consume_graph_answers(graph_meta)
    flags = sibling_flags_from_payload(
        graph_meta,
        multi_id_user_ids=list(answers["multi_id_user_ids"]),
        subject_id=subject_id,
    )
    return {
        "schema_id": SCHEMA_ID,
        "status": "graph:ok",
        "tenant_id": str(tenant_id or ""),
        "subject_id": str(subject_id or ""),
        "named_edges": list(answers["named_edges"]),
        "multi_id_user_ids": list(answers["multi_id_user_ids"]),
        "roles": list(answers["roles"]),
        "sibling_flags": flags,
        "signed_etypes": sorted(signed_pack_etypes(tenant_id)),
        "invented_edges": False,
    }


def _as_stored_hop(
    raw: dict[str, Any],
    *,
    tenant_id: str,
    subject_id: str,
) -> dict[str, Any] | None:
    status = str(raw.get("status") or "")
    if status in _MISSING:
        return _blank_hop(
            status=status or "graph:missing", tenant_id=tenant_id, subject_id=subject_id
        )
    if raw.get("schema_id") == SCHEMA_ID or "signed_etypes" in raw or "sibling_flags" in raw:
        answers = consume_graph_answers(raw)
        flags = raw.get("sibling_flags")
        if not isinstance(flags, dict):
            flags = sibling_flags_from_payload(
                raw,
                multi_id_user_ids=list(answers["multi_id_user_ids"]),
                subject_id=subject_id,
            )
        signed = raw.get("signed_etypes")
        return {
            "schema_id": SCHEMA_ID,
            "status": status or "graph:ok",
            "tenant_id": str(tenant_id or raw.get("tenant_id") or ""),
            "subject_id": str(subject_id or raw.get("subject_id") or ""),
            "named_edges": list(answers["named_edges"]),
            "multi_id_user_ids": list(answers["multi_id_user_ids"]),
            "roles": list(answers["roles"]),
            "sibling_flags": dict(flags) if isinstance(flags, dict) else {},
            "signed_etypes": [str(x) for x in signed] if isinstance(signed, list) else [],
            "invented_edges": False,
        }
    if raw.get("named_edges") is not None or raw.get("multi_id_user_ids") is not None:
        return hop_view_from_graph_meta(
            raw,
            graph_url="snapshot",
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
    return None


def hop_view_from_snapshot(
    snapshot: dict[str, Any] | None,
    *,
    tenant_id: str = "",
    subject_id: str = "",
) -> dict[str, Any]:
    """Replay atoms from a stored hop. Never fetches or invents neighbors."""
    if not isinstance(snapshot, dict):
        return _blank_hop(status="graph:missing", tenant_id=tenant_id, subject_id=subject_id)
    tid = str(tenant_id or snapshot.get("tenant_id") or "")
    sid = str(subject_id or snapshot.get("entity_id") or snapshot.get("subject_id") or "")
    why = snapshot.get("pack_why") if isinstance(snapshot.get("pack_why"), dict) else {}
    candidates: list[Any] = [
        snapshot.get(HOP_FEATURE_KEY),
        snapshot.get("graph_hop_v1"),
        why.get("graph") if isinstance(why, dict) else None,
        snapshot.get("subgraph_snapshot"),
        snapshot.get("inference_context"),
    ]
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("status") or "") in _MISSING:
            return _blank_hop(
                status=str(raw.get("status") or "graph:missing"),
                tenant_id=tid or str(raw.get("tenant_id") or ""),
                subject_id=sid or str(raw.get("entity_id") or ""),
            )
        hop = _as_stored_hop(raw, tenant_id=tid, subject_id=sid)
        if hop is not None:
            return hop
    return _blank_hop(status="graph:empty", tenant_id=tid, subject_id=sid)


def hop_is_present(hop: dict[str, Any] | None) -> bool:
    if not isinstance(hop, dict):
        return False
    return str(hop.get("status") or "") not in _MISSING and hop.get("status") != ""


def eval_graph_v1(
    atom: str,
    hop: dict[str, Any] | None,
    *,
    etype: str | None = None,
    role: str | None = None,
    tenant_id: str = "",
) -> bool:
    if not hop_is_present(hop):
        return False
    assert hop is not None
    tid = str(tenant_id or hop.get("tenant_id") or "")
    if role:
        try:
            require_role(tid, role)
        except UnsignedGraphToken:
            return False
        roles = {str(x).strip().lower() for x in (hop.get("roles") or [])}
        if require_role(tid, role) not in roles:
            return False
    name = str(atom or "").strip()
    if name == "has_etype":
        try:
            want = require_pack_etype(tid, etype or "")
        except UnsignedGraphToken:
            return False
        for edge in hop.get("named_edges") or []:
            if not isinstance(edge, dict):
                continue
            got = canonical_pack_etype(str(edge.get("type") or edge.get("etype") or ""))
            if got == canonical_pack_etype(want):
                return True
        return False
    if name == "has_multi_id":
        return any(str(x).strip() for x in (hop.get("multi_id_user_ids") or []))
    if name == "sibling_prior_flag":
        flags = hop.get("sibling_flags") if isinstance(hop.get("sibling_flags"), dict) else {}
        return any(_positive_flag(v) for v in flags.values())
    return False


def eval_graph_v1_from_features(
    features: dict[str, Any] | None,
    *,
    atom: str,
    etype: str | None = None,
    role: str | None = None,
    tenant_id: str = "",
) -> bool:
    feats = features if isinstance(features, dict) else {}
    hop = feats.get(HOP_FEATURE_KEY)
    hop_dict = hop if isinstance(hop, dict) else None
    tid = tenant_id or str(feats.get("_graph_hop_tenant_id") or "")
    return eval_graph_v1(atom, hop_dict, etype=etype, role=role, tenant_id=tid)


def attach_hop_to_features(features: dict[str, Any], hop: dict[str, Any]) -> dict[str, Any]:
    features[HOP_FEATURE_KEY] = hop
    features["_graph_hop_tenant_id"] = hop.get("tenant_id") or ""
    return features


def fired_graph_v1_atoms(
    hop: dict[str, Any] | None, *, tenant_id: str = ""
) -> list[dict[str, str]]:
    """Atoms that are true on this hop. Empty when the hop is missing."""
    if not hop_is_present(hop):
        return []
    assert hop is not None
    tid = str(tenant_id or hop.get("tenant_id") or "")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for edge in hop.get("named_edges") or []:
        if not isinstance(edge, dict):
            continue
        et = _norm_etype(str(edge.get("type") or edge.get("etype") or ""))
        if not et or et in seen:
            continue
        if eval_graph_v1("has_etype", hop, etype=et, tenant_id=tid):
            seen.add(et)
            out.append({"atom": "has_etype", "etype": et})
    if eval_graph_v1("has_multi_id", hop, tenant_id=tid):
        out.append({"atom": "has_multi_id"})
    if eval_graph_v1("sibling_prior_flag", hop, tenant_id=tid):
        out.append({"atom": "sibling_prior_flag"})
    return out


def named_from_hop(hop: dict[str, Any] | None, *, tenant_id: str = "") -> str:
    if not hop_is_present(hop):
        return "graph:missing"
    parts: list[str] = []
    for item in fired_graph_v1_atoms(hop, tenant_id=tenant_id):
        etype = item.get("etype")
        parts.append(f"{item['atom']}:{etype}" if etype else item["atom"])
    return "+".join(parts) if parts else str((hop or {}).get("status") or "graph:ok")


def pack_why_from_hop(hop: dict[str, Any] | None) -> dict[str, Any]:
    a = (
        hop
        if isinstance(hop, dict)
        else _blank_hop(status="graph:missing", tenant_id="", subject_id="")
    )
    why = pack_why_from_graph_answers(a)
    why["status"] = str(a.get("status") or "graph:missing")
    why["schema_id"] = SCHEMA_ID
    why["sibling_flags"] = dict(a.get("sibling_flags") or {})
    why["signed_etypes"] = list(a.get("signed_etypes") or [])
    why["fired"] = fired_graph_v1_atoms(a)
    why["named"] = named_from_hop(a)
    return why
