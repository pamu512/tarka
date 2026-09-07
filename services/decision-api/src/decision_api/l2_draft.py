"""Leftover / HIL override → Observe pack (mode=shadow) with a backtest gate."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from decision_api.rule_pack_validation import validate_rule_pack

SCHEMA_VERSION = 1
_HUMAN = frozenset({"human", "seed", ""})
_AI_MARKERS = frozenset(
    {"scout", "vllm", "vertex", "ai", "llm", "byom", "assist", "openai", "anthropic"}
)
_CLOSED = frozenset({"abandoned"})


def source_key(*, leftover_id: str = "", hil_event_id: str = "") -> str:
    leftover = (leftover_id or "").strip()
    if leftover:
        return f"leftover:{leftover}"
    return f"hil:{(hil_event_id or '').strip()}"


def compute_pack_hash(pack: dict[str, Any]) -> str:
    payload = json.dumps(
        {"name": pack.get("name"), "mode": pack.get("mode"), "rules": pack.get("rules")},
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
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    leftover = (leftover_id or "").strip()
    hil = (hil_event_id or "").strip()
    if not leftover and not hil:
        raise L2DraftError("source_required", http_status=400, detail="leftover_id or hil_event_id")
    tenant = str(getattr(receipt, "tenant_id", "") or "").strip()
    entity = str(getattr(receipt, "entity_id", "") or "").strip()
    if not tenant or not entity:
        raise L2DraftError("receipt_incomplete", http_status=404, detail="receipt tenant_id/entity_id")
    kind, ai = authored_by_kind(authored_by, is_ai_authored=is_ai_authored, llm_url=llm_url)
    if ai and (skip_backtest or not backtest_ok):
        raise L2DraftError("backtest_required", http_status=409, detail="AI draft needs replay pass")
    who = (actor or "").strip()
    why_skip = (skip_reason or "").strip()
    if skip_backtest and not ai and (not who or not why_skip):
        raise L2DraftError("skip_audit_required", http_status=400, detail="actor and skip_reason")
    built = list(rules) if rules else [
        {
            "id": "leftover_observe",
            "when": [{"field": "entity_id", "op": "eq", "value": entity}],
            "tags": [],
            "score_delta": 5,
            "description": "leftover/override seed; not model-authored",
        }
    ]
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
            "trace_id": str(getattr(receipt, "trace_id", "") or ""),
            "override_why": (override_why or "").strip(),
            "source": "leftover" if leftover else "hil_override",
        },
    }
    errors = validate_rule_pack(pack)
    if errors:
        raise L2DraftError("schema_invalid", http_status=422, detail="; ".join(errors))
    gate = "backtest_passed" if ai else ("backtest_skipped_human" if skip_backtest else "backtest_passed")
    pack["schema_version"] = SCHEMA_VERSION
    pack["source_key"] = source_key(leftover_id=leftover, hil_event_id=hil)
    pack["pack_hash"] = compute_pack_hash(pack)
    pack["lifecycle"] = {
        "state": "observe",
        "gate": gate,
        "backtest_artifact_id": (backtest_artifact_id or "").strip(),
        "skip": (
            {"actor": who, "reason": why_skip, "at": datetime.now(timezone.utc).isoformat()}
            if gate == "backtest_skipped_human"
            else None
        ),
    }
    return pack
