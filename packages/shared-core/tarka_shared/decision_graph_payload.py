"""Shared payload builders for the decision context graph (all writers use this)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

ALLOW_AGE_CAP = 20
MATERIAL_KINDS = frozenset({"human_disposition", "policy_gate"})
MATERIAL_OUTCOMES = frozenset({"deny", "review", "held", "hold"})
DECISION_SOURCES = frozenset({"evaluate", "disposition", "dispute", "ingest"})
DEFAULT_MARKINGS = ["desk"]
_BASED_ON_ORDER = (
    "Payment",
    "Login",
    "Document",
    "LicensePlate",
    "Device",
    "Card",
    "Email",
    "Phone",
    "Address",
    "Session",
    "Ip",
)


def resolve_prior_evaluate_id(tenant_id: str, trace_id: str | None, metadata: dict | None) -> str:
    prior = ""
    if isinstance(metadata, dict):
        prior = str(metadata.get("prior_decision_id") or "").strip()
    if prior:
        return prior
    try:
        from tarka_shared.decision_graph_client import resolve_prior_evaluate_id as _resolve

        return _resolve(tenant_id, trace_id) or ""
    except ImportError:
        return ""


def resolve_prior_agent_advise_id(
    tenant_id: str, case_id: str | None, metadata: dict | None
) -> str:
    prior = ""
    if isinstance(metadata, dict):
        prior = str(metadata.get("prior_decision_id") or "").strip()
    if prior:
        return prior
    try:
        from tarka_shared.decision_graph_client import resolve_prior_agent_advise_id as _resolve

        return _resolve(tenant_id, case_id) or ""
    except ImportError:
        return ""


def resolve_prior_for_disposition(
    tenant_id: str,
    case_id: str,
    trace_id: str | None,
    *,
    agent_run_id: str | None = None,
    explicit_prior: str | None = None,
) -> str:
    prior = (explicit_prior or "").strip()
    if prior:
        return prior
    try:
        from tarka_shared.decision_graph_client import (
            find_latest_failsoft,
            resolve_prior_agent_advise_id,
            resolve_prior_evaluate_id,
        )
    except ImportError:
        return ""
    if agent_run_id:
        row = find_latest_failsoft(tenant_id, agent_run_id=agent_run_id, kind="agent_advise")
        if row:
            return str(row.get("external_id") or "")
    prior = resolve_prior_agent_advise_id(tenant_id, case_id) or ""
    if not prior and trace_id:
        prior = resolve_prior_evaluate_id(tenant_id, trace_id) or ""
    return prior


def _trim(val: Any) -> str:
    return str(val).strip() if val is not None and str(val).strip() else ""


def _device_id(payload: dict[str, Any], device_context: dict[str, Any] | None) -> str:
    if isinstance(device_context, dict):
        did = _trim(device_context.get("device_id"))
        if did:
            return did
    return _trim(payload.get("device_id"))


def _session_id(
    payload: dict[str, Any],
    device_context: dict[str, Any] | None,
    session_id: str | None,
) -> str:
    sid = _trim(session_id)
    if sid:
        return sid
    if isinstance(device_context, dict):
        sid = _trim(device_context.get("session_id"))
        if sid:
            return sid
    return _trim(payload.get("session_id"))


def _first_trimmed(bag: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        val = _trim(bag.get(key))
        if val:
            return val
    return ""


def _email(payload: dict[str, Any]) -> str:
    return _first_trimmed(payload, ("email", "email_address"))


def _phone(payload: dict[str, Any]) -> str:
    return _first_trimmed(payload, ("phone", "phone_number", "mobile"))


def _document_id(payload: dict[str, Any]) -> str:
    return _first_trimmed(payload, ("document_id", "document_number", "doc_id", "document"))


def _license_plate_id(payload: dict[str, Any]) -> tuple[str, str]:
    raw = _first_trimmed(payload, ("license_plate", "licenseplate", "plate"))
    if not raw:
        return "", ""
    oid = raw if raw.startswith("plate:") else f"plate:{raw}"
    return oid, raw


def _instrument_id(prefix: str, raw: str) -> str:
    n = raw.strip().lower()
    if not n:
        return ""
    pfx = f"{prefix}:"
    return n if n.startswith(pfx) else f"{pfx}{n}"


def _address(payload: dict[str, Any]) -> str:
    return _first_trimmed(payload, ("address", "line1", "street_address"))


def _card_id(payload: dict[str, Any]) -> str:
    return _first_trimmed(payload, ("card_id", "card_token"))


def place_cell_id(lat: float, lon: float, precision: int = 3) -> str:
    """Stable coarse place id. Same formula evaluate used for SEEN_AT."""
    return f"cell:{precision}:{round(lat, precision)}:{round(lon, precision)}"


def _geo_lat_lon(
    payload: dict[str, Any], device_context: dict[str, Any] | None
) -> tuple[float, float] | None:
    sig: dict[str, Any] = {}
    if isinstance(device_context, dict):
        raw_sig = device_context.get("signals")
        if isinstance(raw_sig, dict):
            sig = raw_sig
    la_raw = sig.get("geo_lat", payload.get("session_last_lat"))
    lo_raw = sig.get("geo_lon", payload.get("session_last_lon"))
    try:
        la_f = float(la_raw) if la_raw is not None else None
        lo_f = float(lo_raw) if lo_raw is not None else None
    except (TypeError, ValueError):
        return None
    if la_f is None or lo_f is None:
        return None
    if not (-90 <= la_f <= 90 and -180 <= lo_f <= 180):
        return None
    return la_f, lo_f


def _client_ip(payload: dict[str, Any], device_context: dict[str, Any] | None) -> str:
    """Weak identifier. Never used as Person id."""
    if isinstance(device_context, dict):
        sig = device_context.get("signals")
        if isinstance(sig, dict):
            for key in ("ip", "client_ip", "ip_address"):
                val = _trim(sig.get(key))
                if val:
                    return val
        val = _trim(device_context.get("ip"))
        if val:
            return val
    for key in ("ip", "client_ip", "ip_address"):
        val = _trim(payload.get(key))
        if val:
            return val
    return ""


def build_evaluate_objects(
    *,
    trace_id: str,
    entity_id: str,
    event_type: str,
    payload: dict[str, Any] | None,
    device_context: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Person > durable instruments (device, email, phone, doc, card, address) > IP. No Person merge."""
    pl = payload if isinstance(payload, dict) else {}
    et = (event_type or "").strip().lower()
    person_id = _trim(entity_id)
    objects: list[dict[str, Any]] = []
    links: list[dict[str, str]] = []
    if not person_id:
        return objects, links

    def _obj(oid: str, entity_type: str, props: dict[str, Any]) -> None:
        objects.append(
            {
                "external_id": oid,
                "entity_type": entity_type,
                "properties": {
                    **props,
                    "last_trace_id": trace_id,
                    "trace_ids": [trace_id],
                },
            }
        )

    person_props: dict[str, Any] = {"event_type": et}
    email = _email(pl)
    phone = _phone(pl)
    if email:
        person_props["email"] = email
    if phone:
        person_props["phone"] = phone
    _obj(person_id, "Person", person_props)

    # ponytail: identifiers are instruments, same as Device. Person SET overwrites current
    # email/phone; the vertex + HAS_* edge is the ATO hop. Upgrade: first/last seen on the edge.
    if email:
        email_id = _instrument_id("email", email)
        _obj(email_id, "Email", {"email": email.strip().lower()})
        links.append(
            {
                "from_external_id": person_id,
                "to_external_id": email_id,
                "relationship": "HAS_EMAIL",
            }
        )
    if phone:
        phone_id = _instrument_id("phone", phone)
        _obj(phone_id, "Phone", {"phone": phone.strip().lower()})
        links.append(
            {
                "from_external_id": person_id,
                "to_external_id": phone_id,
                "relationship": "HAS_PHONE",
            }
        )
    addr = _address(pl)
    if addr:
        addr_id = _instrument_id("addr", addr)
        _obj(addr_id, "Address", {"address": addr.strip().lower()})
        links.append(
            {"from_external_id": person_id, "to_external_id": addr_id, "relationship": "USED"}
        )
    card = _card_id(pl)
    if card:
        card_oid = _instrument_id("card", card)
        _obj(card_oid, "Card", {"card_id": card.strip().lower()})
        links.append(
            {"from_external_id": person_id, "to_external_id": card_oid, "relationship": "HAS_CARD"}
        )

    acct = _trim(pl.get("account_id"))
    if acct and acct != person_id:
        _obj(acct, "Account", {})
        links.append(
            {"from_external_id": person_id, "to_external_id": acct, "relationship": "OWNS"}
        )

    device_id = _device_id(pl, device_context)
    if device_id:
        _obj(device_id, "Device", {})
        links.append(
            {
                "from_external_id": person_id,
                "to_external_id": device_id,
                "relationship": "USED_DEVICE",
            }
        )

    sess = _session_id(pl, device_context, session_id)
    sess_id = f"sess:{sess}" if sess else ""
    if sess_id:
        _obj(sess_id, "Session", {"session_id": sess})
        links.append(
            {
                "from_external_id": person_id,
                "to_external_id": sess_id,
                "relationship": "USED_SESSION",
            }
        )

    doc_id = _document_id(pl)
    if doc_id:
        _obj(doc_id, "Document", {})
        links.append(
            {"from_external_id": person_id, "to_external_id": doc_id, "relationship": "USED"}
        )

    plate_id, plate_raw = _license_plate_id(pl)
    if plate_id:
        _obj(plate_id, "LicensePlate", {"license_plate": plate_raw})
        links.append(
            {"from_external_id": person_id, "to_external_id": plate_id, "relationship": "USED"}
        )

    event_id = ""
    if et == "payment":
        event_id = _trim(pl.get("payment_id")) or f"pay:{trace_id}"
        pay_props: dict[str, Any] = {}
        if pl.get("amount") is not None:
            pay_props["amount"] = pl.get("amount")
        if _trim(pl.get("currency")):
            pay_props["currency"] = _trim(pl.get("currency"))
        _obj(event_id, "Payment", pay_props)
        links.append(
            {
                "from_external_id": person_id,
                "to_external_id": event_id,
                "relationship": "MADE_PAYMENT",
            }
        )
    elif et == "login":
        event_id = f"login:{trace_id}"
        _obj(event_id, "Login", {})
        links.append(
            {
                "from_external_id": person_id,
                "to_external_id": event_id,
                "relationship": "PERFORMED_LOGIN",
            }
        )

    if event_id and sess_id:
        links.append(
            {
                "from_external_id": event_id,
                "to_external_id": sess_id,
                "relationship": "USED_SESSION",
            }
        )

    # Person > Device|Payment|Document|LicensePlate > IP. Evaluate hangs under the instrument that had it.
    if et == "payment" and event_id:
        mid_id = event_id
    elif et == "login" and device_id:
        mid_id = device_id
    elif doc_id:
        mid_id = doc_id
    elif plate_id:
        mid_id = plate_id
    elif device_id:
        mid_id = device_id
    else:
        mid_id = ""

    # ponytail: IP is a clue only. Never Person id. Coffee-shop NAT is not one actor.
    client_ip = _client_ip(pl, device_context)
    ip_id = f"ip:{client_ip}" if client_ip else ""
    if ip_id:
        _obj(ip_id, "Ip", {"ip": client_ip})
        links.append(
            {
                "from_external_id": mid_id or person_id,
                "to_external_id": ip_id,
                "relationship": "USED_IP",
            }
        )

    geo = _geo_lat_lon(pl, device_context)
    if geo:
        la_f, lo_f = geo
        cell = place_cell_id(la_f, lo_f)
        _obj(
            cell,
            "Place",
            {
                "kind": "geohash_like_cell",
                "lat": round(la_f, 5),
                "lon": round(lo_f, 5),
            },
        )
        links.append(
            {
                "from_external_id": person_id,
                "to_external_id": cell,
                "relationship": "SEEN_AT",
            }
        )

    return objects, links


def resolve_decision_source(metadata: dict[str, Any] | None, *, default: str = "evaluate") -> str:
    raw = ""
    if isinstance(metadata, dict):
        raw = str(metadata.get("decision_source") or "").strip().lower()
    if raw in DECISION_SOURCES:
        return raw
    fb = (default or "evaluate").strip().lower()
    return fb if fb in DECISION_SOURCES else "evaluate"


def normalize_markings(raw: Any) -> list[str]:
    if raw is None:
        return list(DEFAULT_MARKINGS)
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        return list(DEFAULT_MARKINGS)
    out: list[str] = []
    for item in items:
        s = str(item or "").strip().lower()
        if s and s not in out:
            out.append(s)
    # Explicit [] stays hidden. None / garbage still default to desk.
    if isinstance(raw, list):
        return out
    return out or list(DEFAULT_MARKINGS)


def is_material_decision(kind: str, outcome: str) -> bool:
    if (kind or "").strip().lower() in MATERIAL_KINDS:
        return True
    o = (outcome or "").strip().lower()
    return o in MATERIAL_OUTCOMES or o.startswith("resolved")


def decision_external_id(trace_id: str | None, *, explicit: str | None = None) -> str:
    if (explicit or "").strip():
        return str(explicit).strip()
    t = _trim(trace_id)
    return f"dec:{t}" if t else ""


def _based_on_id(objects: list[dict[str, Any]]) -> str:
    by_type = {
        str(obj.get("entity_type") or ""): str(obj.get("external_id") or "").strip()
        for obj in objects
        if str(obj.get("entity_type") or "") != "Decision"
    }
    for kind in _BASED_ON_ORDER:
        if by_type.get(kind):
            return by_type[kind]
    return ""


def attach_decision_object(
    objects: list[dict[str, Any]],
    links: list[dict[str, str]],
    *,
    person_id: str,
    trace_id: str | None,
    outcome: str,
    kind: str,
    source: str,
    external_id: str | None = None,
    created_at: str | None = None,
    rule_ids: list[str] | None = None,
    markings: list[str] | None = None,
) -> str:
    """Person-RESULTED_IN-Decision and Decision-BASED_ON-instrument."""
    person = _trim(person_id)
    dec_id = decision_external_id(trace_id, explicit=external_id)
    if not person or not dec_id:
        return ""
    if any(str(obj.get("external_id") or "") == dec_id for obj in objects):
        return dec_id
    now = created_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    objects.append(
        {
            "external_id": dec_id,
            "entity_type": "Decision",
            "properties": {
                "kind": kind,
                "source": source,
                "outcome": str(outcome or ""),
                "trace_id": _trim(trace_id),
                "created_at": now,
                "markings": normalize_markings(markings),
                "rule_ids": list(rule_ids or [])[:32],
                "last_trace_id": _trim(trace_id),
                "trace_ids": [_trim(trace_id)] if _trim(trace_id) else [],
            },
        }
    )
    links.append(
        {
            "from_external_id": person,
            "to_external_id": dec_id,
            "relationship": "RESULTED_IN",
        }
    )
    based = _based_on_id(objects)
    if based:
        links.append(
            {
                "from_external_id": dec_id,
                "to_external_id": based,
                "relationship": "BASED_ON",
            }
        )
    return dec_id


def allow_decision_ids_over_cap(
    nodes: list[dict[str, Any]],
    *,
    cap: int = ALLOW_AGE_CAP,
) -> list[str]:
    """Oldest evaluate-allow Decision ids past the rolling window. Material stays."""
    allows: list[tuple[str, str]] = []
    for node in nodes:
        labels = node.get("labels") or []
        etype = str(node.get("entity_type") or "")
        if etype != "Decision" and "Decision" not in [str(x) for x in labels]:
            continue
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        kind = str(props.get("kind") or "")
        outcome = str(props.get("outcome") or "")
        source = str(props.get("source") or "").lower()
        if is_material_decision(kind, outcome):
            continue
        if source != "evaluate" or outcome.strip().lower() != "allow":
            continue
        eid = str(
            node.get("id") or node.get("external_id") or props.get("external_id") or ""
        ).strip()
        if not eid:
            continue
        allows.append((str(props.get("created_at") or ""), eid))
    allows.sort(key=lambda row: (row[0], row[1]))
    if len(allows) <= cap:
        return []
    return [eid for _, eid in allows[:-cap]]


def evaluate_related_object_refs(
    *,
    trace_id: str,
    entity_id: str,
    event_type: str,
    payload: dict[str, Any] | None,
    device_context: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> list[dict[str, str]]:
    """Non-Person objects on this evaluate. Pack attention looks these up; never the Person mash."""
    objects, _links = build_evaluate_objects(
        trace_id=trace_id,
        entity_id=entity_id,
        event_type=event_type,
        payload=payload,
        device_context=device_context,
        session_id=session_id,
    )
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for obj in objects:
        kind = str(obj.get("entity_type") or "")
        eid = str(obj.get("external_id") or "").strip()
        if not eid or kind in {"Person", "Decision"} or eid in seen:
            continue
        seen.add(eid)
        refs.append({"external_id": eid, "entity_type": kind or "Custom"})
    return refs


def build_evaluate_payload(
    *,
    tenant_id: str,
    trace_id: str,
    entity_id: str,
    event_type: str,
    decision: str,
    score: float,
    rule_hits: list[str] | None,
    fallback_reason: str | None,
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    decision_log_record: dict[str, Any] | None,
    shadow_request: bool,
    device_context: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    prior = resolve_prior_evaluate_id(tenant_id, trace_id, metadata)
    edges: list[dict[str, str]] = []
    if prior:
        edges.append({"from_external_id": prior, "relationship": "INFLUENCED"})
    reasoning_parts: list[str] = []
    if rule_hits:
        reasoning_parts.append("rules=" + ",".join(rule_hits[:12]))
    if fallback_reason:
        reasoning_parts.append(f"fallback={fallback_reason}")
    objects, object_links = build_evaluate_objects(
        trace_id=trace_id,
        entity_id=entity_id,
        event_type=event_type,
        payload=payload,
        device_context=device_context,
        session_id=session_id,
    )
    outcome = str(decision or "").strip()
    dec_id = attach_decision_object(
        objects,
        object_links,
        person_id=entity_id,
        trace_id=trace_id,
        outcome=outcome,
        kind="evaluate",
        source=resolve_decision_source(metadata if isinstance(metadata, dict) else None),
        rule_ids=list(rule_hits or []),
        markings=normalize_markings(
            metadata.get("markings") if isinstance(metadata, dict) else None
        ),
    )
    if prior and dec_id:
        object_links.append(
            {
                "from_external_id": dec_id,
                "to_external_id": prior,
                "relationship": "SUPERSEDES",
            }
        )
    if outcome:
        for obj in objects:
            props = obj.get("properties")
            if isinstance(props, dict):
                props["last_outcome"] = outcome
    entity_ids = [o["external_id"] for o in objects]
    pl = payload if isinstance(payload, dict) else {}
    for key in ("device_id", "account_id", "payment_id", "user_id"):
        val = pl.get(key)
        if val and str(val) not in entity_ids:
            entity_ids.append(str(val))
    audit_log_id = None
    if isinstance(decision_log_record, dict):
        audit_log_id = (
            str(
                decision_log_record.get("audit_log_id") or decision_log_record.get("id") or ""
            ).strip()
            or None
        )
    evidence_ids: list[str] = []
    return {
        "tenant_id": tenant_id,
        "kind": "evaluate",
        "category": "transaction_evaluate",
        "scenario": f"{event_type}:{entity_id}",
        "outcome": str(decision),
        "reasoning": "; ".join(reasoning_parts) or "evaluate",
        "confidence": float(score) if score is not None else None,
        "rule_ids": list(rule_hits or [])[:32],
        "entity_external_ids": entity_ids[:32],
        "objects": objects,
        "object_links": object_links,
        "trace_id": trace_id,
        "audit_log_id": audit_log_id,
        "evidence_ids": evidence_ids,
        "shadow": bool(shadow_request),
        "edges": edges,
    }


def build_agent_advise_payload(
    *,
    tenant_id: str,
    run_id: str,
    case_id: str | None,
    entity_ids: list[str] | None,
    trace_ids: list[str] | None,
    claims: list[dict[str, Any]] | None,
    context_snapshot: dict[str, Any] | None,
    source: str,
) -> dict[str, Any]:
    prior = ""
    if isinstance(context_snapshot, dict):
        prior = str(context_snapshot.get("prior_decision_id") or "").strip()
    if not prior and trace_ids:
        prior = resolve_prior_evaluate_id(tenant_id, str(trace_ids[0]), context_snapshot)
    edges: list[dict[str, str]] = []
    if prior:
        edges.append({"from_external_id": prior, "relationship": "INFLUENCED"})
    evidence: list[str] = []
    for claim in claims or []:
        if not isinstance(claim, dict):
            continue
        for eid in claim.get("evidence_ids") or []:
            s = str(eid).strip()
            if s and s not in evidence:
                evidence.append(s)
    outcome = "advise"
    if claims:
        outcome = str((claims[0] or {}).get("claim") or (claims[0] or {}).get("text") or "advise")[
            :128
        ]
    return {
        "tenant_id": (tenant_id or "").strip(),
        "kind": "agent_advise",
        "category": f"agent_run:{source}",
        "scenario": f"agent_run case={case_id or '-'}",
        "outcome": outcome or "advise",
        "reasoning": f"agent_run_id={run_id}; claims={len(claims or [])}",
        "agent_run_id": run_id,
        "case_id": case_id,
        "trace_id": (trace_ids or [None])[0],
        "entity_external_ids": list(entity_ids or [])[:32],
        "evidence_ids": evidence[:64],
        "edges": edges,
    }


def build_human_disposition_payload(
    *,
    tenant_id: str,
    case_id: str,
    entity_id: str | None,
    trace_id: str | None,
    status: str,
    actor_id: str,
    reason_code: str | None,
    prior_decision_id: str | None = None,
    agent_run_id: str | None = None,
) -> dict[str, Any]:
    prior = resolve_prior_for_disposition(
        tenant_id,
        case_id,
        trace_id,
        agent_run_id=agent_run_id,
        explicit_prior=prior_decision_id,
    )
    edges: list[dict[str, str]] = []
    if prior:
        edges.append({"from_external_id": prior, "relationship": "CAUSED"})
    objects: list[dict[str, Any]] = []
    object_links: list[dict[str, str]] = []
    person_id = _trim(entity_id)
    if person_id:
        objects.append(
            {
                "external_id": person_id,
                "entity_type": "Person",
                "properties": {"last_act": str(status)},
            }
        )
    tid = _trim(trace_id)
    disp_id = f"dec:disp:{case_id}:{tid or uuid.uuid4().hex[:12]}"
    attach_decision_object(
        objects,
        object_links,
        person_id=person_id,
        trace_id=trace_id,
        outcome=str(status),
        kind="human_disposition",
        source="disposition",
        external_id=disp_id,
        markings=normalize_markings(None),
    )
    if prior:
        object_links.append(
            {
                "from_external_id": disp_id,
                "to_external_id": prior,
                "relationship": "SUPERSEDES",
            }
        )
    return {
        "tenant_id": tenant_id,
        "kind": "human_disposition",
        "category": "case_status",
        "scenario": f"case {case_id} → {status}",
        "outcome": str(status),
        "reasoning": f"actor={actor_id}" + (f"; reason={reason_code}" if reason_code else ""),
        "case_id": case_id,
        "entity_external_ids": [person_id] if person_id else [],
        "objects": objects,
        "object_links": object_links,
        "trace_id": trace_id,
        "edges": edges,
    }
