"""Leftover / HIL override → Observe pack (mode=shadow) with a backtest gate."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from decision_api.rule_pack_validation import validate_rule_pack

SCHEMA_VERSION = 1
OVERRIDE_WHY_MIN = 8
_HUMAN = frozenset({"human", "seed", ""})
_AI_MARKERS = frozenset(
    {"scout", "vllm", "vertex", "ai", "llm", "byom", "assist", "openai", "anthropic"}
)
_CLOSED = frozenset({"abandoned", "promoted"})
_DEMOTE_PREFIXES = ("scout", "byom", "llm", "vllm", "vertex", "openai", "anthropic")
DEMOTE_PROPOSED = "proposed"
DEMOTE_CONFIRMED = "confirmed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_key(*, leftover_id: str = "", hil_event_id: str = "") -> str:
    leftover = (leftover_id or "").strip()
    if leftover:
        return f"leftover:{leftover}"
    return f"hil:{(hil_event_id or '').strip()}"


def compute_pack_hash(pack: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "name": pack.get("name"),
            "mode": pack.get("mode"),
            "rules": pack.get("rules"),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_open_draft(
    packs: list[dict[str, Any]],
    *,
    leftover_id: str = "",
    hil_event_id: str = "",
) -> dict[str, Any] | None:
    want = source_key(leftover_id=leftover_id, hil_event_id=hil_event_id)
    if want.endswith(":"):
        return None
    for pack in packs:
        ev = pack.get("evidence") or {}
        key = str(pack.get("source_key") or "").strip() or source_key(
            leftover_id=str(ev.get("leftover_id") or ""),
            hil_event_id=str(ev.get("hil_event_id") or ""),
        )
        state = str((pack.get("lifecycle") or {}).get("state") or "observe")
        if key == want and state not in _CLOSED:
            return pack
    return None


class L2DraftError(Exception):
    def __init__(self, code: str, *, http_status: int, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.http_status = http_status
        self.detail = detail or code


def _field(obj: Any, name: str) -> str:
    if isinstance(obj, dict):
        return str(obj.get(name) or "").strip()
    return str(getattr(obj, name, "") or "").strip()


def authored_by_kind(
    authored_by: str,
    *,
    is_ai_authored: bool,
    llm_url: str,
) -> tuple[str, bool]:
    raw = (authored_by or "").strip()
    token = raw.lower()
    llm = (llm_url or "").strip()
    if not llm:
        if token in _HUMAN:
            return token, False
        return "human", False
    looks_ai = is_ai_authored or token in _AI_MARKERS
    if looks_ai:
        return (token or "scout"), True
    if token in _HUMAN:
        return token, False
    return "human", False


def build_l2_draft(
    *,
    receipt: Any,
    leftover_id: str = "",
    hil_event_id: str = "",
    override_why: str = "",
    authored_by: str = "",
    is_ai_authored: bool = False,
    llm_url: str = "",
    skip_backtest: bool = False,
    backtest_ok: bool = False,
    backtest_artifact_id: str = "",
    actor: str = "",
    skip_reason: str = "",
    intent: str = "",
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    leftover = (leftover_id or "").strip()
    hil = (hil_event_id or "").strip()
    if not leftover and not hil:
        raise L2DraftError(
            "source_required", http_status=400, detail="leftover_id or hil_event_id"
        )
    tenant = _field(receipt, "tenant_id")
    entity = _field(receipt, "entity_id") or _field(receipt, "user_id")
    if not tenant or not entity:
        raise L2DraftError(
            "receipt_incomplete", http_status=404, detail="receipt tenant_id/entity_id"
        )
    kind, ai = authored_by_kind(
        authored_by, is_ai_authored=is_ai_authored, llm_url=llm_url
    )
    if ai and (skip_backtest or not backtest_ok):
        raise L2DraftError(
            "backtest_required", http_status=409, detail="AI draft needs replay pass"
        )
    who = (actor or "").strip()
    why_skip = (skip_reason or "").strip()
    if skip_backtest and not ai and (not who or not why_skip):
        raise L2DraftError(
            "skip_audit_required", http_status=400, detail="actor and skip_reason"
        )
    why = (override_why or "").strip()
    if leftover and len(why) < OVERRIDE_WHY_MIN:
        raise L2DraftError(
            "why_required",
            http_status=400,
            detail=f"override_why must be at least {OVERRIDE_WHY_MIN} characters",
        )
    soften = (intent or "").strip().lower() == "soften"
    built = (
        list(rules)
        if rules
        else [
            {
                "id": "leftover_soften" if soften else "leftover_observe",
                "when": [{"field": "entity_id", "op": "eq", "value": entity}],
                "tags": [],
                "score_delta": -5 if soften else 5,
                "description": (
                    "fp soften seed; not model-authored"
                    if soften
                    else "leftover/override seed; not model-authored"
                ),
            }
        ]
    )
    source = leftover or hil
    name = f"l2_{source}"[:80]
    pack: dict[str, Any] = {
        "version": 1,
        "name": name,
        "mode": "shadow",
        "rules": built,
        "tag_rules": [],
        "authored_by": kind,
        "is_ai_authored": ai,
        "tenant_id": tenant,
        "evidence": {
            "leftover_id": leftover,
            "hil_event_id": hil,
            "trace_id": _field(receipt, "trace_id"),
            "override_why": (override_why or "").strip(),
            "source": "leftover" if leftover else "hil_override",
            "intent": "soften" if soften else "",
        },
    }
    errors = validate_rule_pack(pack)
    if errors:
        raise L2DraftError("schema_invalid", http_status=422, detail="; ".join(errors))
    gate = (
        "backtest_passed"
        if ai
        else ("backtest_skipped_human" if skip_backtest else "backtest_passed")
    )
    pack["schema_version"] = SCHEMA_VERSION
    pack["source_key"] = source_key(leftover_id=leftover, hil_event_id=hil)
    pack["pack_hash"] = compute_pack_hash(pack)
    stamped = _now()
    pack["lifecycle"] = {
        "state": "observe",
        "gate": gate,
        "backtest_artifact_id": (backtest_artifact_id or "").strip(),
        "created_at": stamped,
        "observe_entered_at": stamped,
        "skip": (
            {"actor": who, "reason": why_skip, "at": stamped}
            if gate == "backtest_skipped_human"
            else None
        ),
    }
    return pack


def abandon_draft(pack: dict[str, Any], *, actor: str = "") -> dict[str, Any]:
    life = dict(pack.get("lifecycle") or {})
    if str(life.get("state") or "") in _CLOSED:
        raise L2DraftError(
            "draft_closed", http_status=409, detail="draft already closed"
        )
    who = (actor or "").strip()
    if not who:
        raise L2DraftError("actor_required", http_status=400, detail="actor")
    life["state"] = "abandoned"
    life["abandoned_at"] = _now()
    life["abandoned_by"] = who
    pack["lifecycle"] = life
    return pack


def mark_promoted(pack: dict[str, Any]) -> dict[str, Any]:
    life = dict(pack.get("lifecycle") or {})
    life["state"] = "promoted"
    life["promoted_at"] = _now()
    pack["lifecycle"] = life
    return pack


def is_forbidden_demote_actor(actor: str) -> bool:
    """Scout / assist / BYO LLM fingerprints cannot propose or confirm demote."""
    token = (actor or "").strip().lower()
    if not token or "assist" in token:
        return True
    if token in {"ai", "llm", "byom"}:
        return True
    return any(token.startswith(p) for p in _DEMOTE_PREFIXES)


def _demote_blob(pack: dict[str, Any]) -> dict[str, Any]:
    life = pack.get("lifecycle") if isinstance(pack.get("lifecycle"), dict) else {}
    blob = life.get("demote") if isinstance(life.get("demote"), dict) else {}
    return dict(blob)


def _require_demote_audit(actor: str, reason: str) -> tuple[str, str]:
    who = (actor or "").strip()
    why = (reason or "").strip()
    if not who or not why:
        raise L2DraftError(
            "demote_audit_required", http_status=400, detail="actor and reason"
        )
    return who, why


def propose_demote(pack: dict[str, Any], *, actor: str, reason: str) -> dict[str, Any]:
    """Park a human demote proposal. Live mode stays on. No auto-demote."""
    mode = str(pack.get("mode") or "active")
    if mode not in {"active", ""}:
        raise L2DraftError("not_live", http_status=409, detail="not_live")
    who, why = _require_demote_audit(actor, reason)
    blob = _demote_blob(pack)
    state = str(blob.get("state") or "")
    if state == DEMOTE_PROPOSED:
        raise L2DraftError(
            "demote_already_proposed", http_status=409, detail="demote_already_proposed"
        )
    if state == DEMOTE_CONFIRMED:
        raise L2DraftError("already_demoted", http_status=409, detail="already_demoted")
    raw_life = pack.get("lifecycle")
    life = dict(raw_life) if isinstance(raw_life, dict) else {}
    life["demote"] = {
        "state": DEMOTE_PROPOSED,
        "proposed_by": who,
        "proposed_reason": why,
        "proposed_at": _now(),
    }
    pack["lifecycle"] = life
    return pack


def confirm_demote(pack: dict[str, Any], *, actor: str, reason: str) -> dict[str, Any]:
    """Human confirm: flip live pack to Observe. Requires a parked proposal."""
    mode = str(pack.get("mode") or "active")
    if mode not in {"active", ""}:
        raise L2DraftError("not_live", http_status=409, detail="not_live")
    who, why = _require_demote_audit(actor, reason)
    blob = _demote_blob(pack)
    if str(blob.get("state") or "") != DEMOTE_PROPOSED:
        raise L2DraftError(
            "demote_propose_first", http_status=409, detail="demote_propose_first"
        )
    blob["state"] = DEMOTE_CONFIRMED
    blob["confirmed_by"] = who
    blob["confirmed_reason"] = why
    blob["confirmed_at"] = _now()
    raw_life = pack.get("lifecycle")
    life = dict(raw_life) if isinstance(raw_life, dict) else {}
    life["demote"] = blob
    pack["lifecycle"] = life
    pack["mode"] = "shadow"
    return pack
