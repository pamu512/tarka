"""Assemble the fixed Advise evidence pack. The model does not choose fields."""

from __future__ import annotations

import json
import math
from typing import Any

MISSING = "missing"

_MAX_PACK_CHARS = 4000
_MAX_HOPS = 8
_MAX_HITS = 32
_MAX_HIT_CHARS = 64
_MAX_WHY_CHARS = 240
_MAX_OKF = 8
_MAX_ID_CHARS = 128


def _looks_like_email(text: str) -> bool:
    # Linear: local@domain.tld. No regex — CodeQL flagged the % class-plus pattern.
    at = text.find("@")
    if at < 1:
        return False
    rest = text[at + 1 :]
    dot = rest.find(".")
    return dot > 0 and dot < len(rest) - 1


def _looks_like_pan(text: str) -> bool:
    digits = 0
    for ch in text:
        if ch.isdigit():
            digits += 1
            if digits >= 13:
                return True
        elif ch not in " -":
            digits = 0
    return False


def _text(value: Any, limit: int = _MAX_ID_CHARS) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    if not cleaned:
        return ""
    # Cap first so PII scans never walk unbounded leftover/audit strings.
    if len(cleaned) > limit:
        cleaned = cleaned[:limit]
    if _looks_like_email(cleaned) or _looks_like_pan(cleaned):
        return ""
    return cleaned


def _amount(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _first_text(*values: Any, limit: int = _MAX_ID_CHARS) -> str:
    for value in values:
        text = _text(value, limit)
        if text:
            return text
    return ""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _pack_id_from_file(value: Any) -> str:
    text = _text(value, 256)
    if not text:
        return ""
    name = text.rsplit("/", 1)[-1]
    if name.endswith(".json"):
        name = name[: -len(".json")]
    return _text(name, _MAX_ID_CHARS)


def _rule_hits(audit: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    raw = audit.get("rule_hits")
    if not isinstance(raw, list):
        raw = payload.get("rule_hits")
    if not isinstance(raw, list):
        return []
    hits: list[str] = []
    for item in raw:
        text = _text(item, _MAX_HIT_CHARS)
        if text:
            hits.append(text)
        if len(hits) >= _MAX_HITS:
            break
    return hits


def _receipt_why(audit: dict[str, Any] | None) -> dict[str, Any]:
    """Pack id + rule hits. Missing why is the literal ``missing`` — never invented."""
    audit_d = _as_dict(audit)
    payload = _as_dict(audit_d.get("evaluate_payload"))
    pack_id = _first_text(
        audit_d.get("pack_id"),
        payload.get("pack_id"),
        _pack_id_from_file(audit_d.get("rule_pack_file")),
        _pack_id_from_file(payload.get("rule_pack_file")),
    )
    hits = _rule_hits(audit_d, payload)
    why = _first_text(
        audit_d.get("pack_reason"),
        payload.get("pack_reason"),
        audit_d.get("pack_why"),
        payload.get("pack_why"),
        limit=_MAX_WHY_CHARS,
    )
    if not why and hits:
        why = _text(", ".join(hits), _MAX_WHY_CHARS)
    return {
        "pack_id": pack_id or MISSING,
        "rule_hits": hits,
        "why": why or MISSING,
    }


def _flags(case: dict[str, Any] | None, audit: dict[str, Any] | None) -> dict[str, bool]:
    labels = _as_dict(case).get("labels")
    tokens: set[str] = set()
    if isinstance(labels, list):
        for item in labels:
            text = _text(item, 64).lower()
            if text:
                tokens.add(text)
    audit_d = _as_dict(audit)
    override = "override" in tokens or audit_d.get("override") is True
    late = (
        "late_label" in tokens
        or "late-label" in tokens
        or audit_d.get("late_label") is True
        or bool(_text(audit_d.get("y_label"), 64))
    )
    return {"override": bool(override), "late_label": bool(late)}


def hop_labels(graph: dict[str, Any] | None, *, limit: int = _MAX_HOPS) -> list[dict[str, str]]:
    """Last N hop labels: ids and types only. Drops property blobs."""
    edges = _as_dict(graph).get("edges")
    if not isinstance(edges, list):
        return []
    hops: list[dict[str, str]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        etype = _text(edge.get("type") or edge.get("etype"), 64)
        src = _text(edge.get("from_id") or edge.get("src") or edge.get("id"), _MAX_ID_CHARS)
        dst = _text(edge.get("to_id") or edge.get("dst"), _MAX_ID_CHARS)
        if not etype or not src:
            continue
        hop_id = f"{src}->{dst}" if dst else src
        hops.append({"id": hop_id[:_MAX_ID_CHARS], "type": etype})
    if limit < 1:
        return []
    return hops[-limit:]


def _okf_ids(raw: list[Any] | None) -> list[str]:
    if not raw:
        return []
    ids: list[str] = []
    for item in raw:
        text = _text(item, 64)
        if text and text not in ids:
            ids.append(text)
        if len(ids) >= _MAX_OKF:
            break
    return ids


def _lookup_amount(*sources: dict[str, Any]) -> int | float | None:
    for source in sources:
        for key in ("amount", "txn_amount"):
            amount = _amount(source.get(key))
            if amount is not None:
                return amount
        payload = _as_dict(source.get("payload"))
        amount = _amount(payload.get("amount"))
        if amount is not None:
            return amount
    return None


def _lookup_event_type(*sources: dict[str, Any]) -> str:
    for source in sources:
        text = _text(source.get("event_type"), 64)
        if text:
            return text
    return ""


def build_evidence_pack(
    *,
    tenant_id: str,
    case: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
    okf_chunk_ids: list[Any] | None = None,
) -> dict[str, Any]:
    """Allowlisted leftover summary + evaluate receipt why + optional hop/OKF ids."""
    case_d = _as_dict(case)
    audit_d = _as_dict(audit)
    payload = _as_dict(audit_d.get("evaluate_payload"))
    sources = (case_d, audit_d, payload, _as_dict(audit_d.get("payload")))
    leftover: dict[str, Any] = {
        "case_id": _first_text(case_d.get("id"), case_d.get("case_id")),
        "tenant_id": _first_text(tenant_id, case_d.get("tenant_id"), audit_d.get("tenant_id")),
        "entity_id": _first_text(case_d.get("entity_id"), audit_d.get("entity_id")),
        "trace_id": _first_text(case_d.get("trace_id"), audit_d.get("trace_id"), limit=64),
    }
    amount = _lookup_amount(*sources)
    if amount is not None:
        leftover["amount"] = amount
    event_type = _lookup_event_type(*sources)
    if event_type:
        leftover["event_type"] = event_type
    pack = {
        "leftover": leftover,
        "receipt": _receipt_why(audit_d or None),
        "flags": _flags(case_d or None, audit_d or None),
        "hops": hop_labels(graph),
        "okf_chunk_ids": _okf_ids(okf_chunk_ids),
    }
    return _cap_pack(pack)


def is_thin_evidence(pack: dict[str, Any]) -> bool:
    """No leftover body and no evaluate receipt → do not call Jev or the LLM."""
    leftover = _as_dict(pack.get("leftover"))
    has_body = any(
        (
            _text(leftover.get("case_id")),
            _text(leftover.get("entity_id")),
            _text(leftover.get("trace_id"), 64),
            _text(leftover.get("event_type"), 64),
            leftover.get("amount") is not None,
        )
    )
    receipt = _as_dict(pack.get("receipt"))
    has_receipt = (
        _text(receipt.get("pack_id")) not in ("", MISSING)
        or bool(receipt.get("rule_hits"))
        or _text(receipt.get("why"), _MAX_WHY_CHARS) not in ("", MISSING)
    )
    return not has_body and not has_receipt


def _cap_pack(pack: dict[str, Any]) -> dict[str, Any]:
    """ponytail: drop hops, then OKF ids, then hits, then why. Ceiling 4000 chars."""

    def size() -> int:
        return len(json.dumps(pack, sort_keys=True, separators=(",", ":"), default=str))

    if size() <= _MAX_PACK_CHARS:
        return pack
    pack["hops"] = []
    if size() <= _MAX_PACK_CHARS:
        return pack
    pack["okf_chunk_ids"] = []
    if size() <= _MAX_PACK_CHARS:
        return pack
    hits = pack.get("receipt", {}).get("rule_hits")
    if isinstance(hits, list) and hits:
        pack["receipt"]["rule_hits"] = hits[:8]
        if pack["receipt"].get("why") not in (None, "", MISSING):
            joined = _text(", ".join(pack["receipt"]["rule_hits"]), _MAX_WHY_CHARS)
            explicit = pack["receipt"].get("why")
            if isinstance(explicit, str) and explicit == ", ".join(hits):
                pack["receipt"]["why"] = joined or MISSING
    if size() <= _MAX_PACK_CHARS:
        return pack
    if isinstance(pack.get("receipt"), dict):
        pack["receipt"]["why"] = MISSING
        pack["receipt"]["rule_hits"] = []
    return pack


def pack_contains_bait(pack: dict[str, Any], *bait: str) -> bool:
    raw = json.dumps(pack, default=str)
    return any(item and item in raw for item in bait)
