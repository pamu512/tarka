from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from decision_api.config import settings
from decision_api.rule_label_metrics import rule_precision_after_labels

MIX_FIELDS = ("event_type", "geo_country", "device_fingerprint", "canvas_hash")
LEGAL_WHEN_FIELDS = frozenset(MIX_FIELDS)
MIN_HALF = 50
MIN_HITS = 5
MIN_MISSES = 5

_SAFE = re.compile(r"[^A-Za-z0-9_]+")


def resolve_y(
    row: Mapping[str, Any],
    by_trace: Mapping[str, str],
    by_entity: Mapping[str, str],
) -> str | None:
    tid = str(row.get("trace_id") or "").strip()
    eid = str(row.get("entity_id") or "").strip()
    lab = by_trace.get(tid) if tid else None
    if lab not in {"0", "1"}:
        lab = by_entity.get(eid) if eid else None
    return lab if lab in {"0", "1"} else None


def mix_value(row: Mapping[str, Any], field: str) -> str:
    if field == "event_type":
        return str(row.get("event_type") or "").strip()
    snap = row.get("payload_snapshot")
    payload = snap.get("payload") if isinstance(snap, Mapping) else None
    blob = payload if isinstance(payload, Mapping) else snap if isinstance(snap, Mapping) else {}
    return str(blob.get(field) or "").strip()


def split_window(rows: Sequence[Mapping[str, Any]]) -> tuple[list, list, str]:
    items = [r for r in rows if isinstance(r, Mapping)]
    mid = len(items) // 2
    current, prior = list(items[:mid]), list(items[mid:])
    if len(current) < MIN_HALF or len(prior) < MIN_HALF:
        return current, prior, "underpowered"
    return current, prior, "ok"


def _hits(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("rule_hits")
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _rate(rule_id: str, half: Sequence[Mapping[str, Any]]) -> tuple[float, int]:
    n = len(half)
    h = sum(1 for r in half if rule_id in _hits(r))
    return ((h / n) if n else 0.0, h)


def _fire_rate_on(rule_id: str, current: Sequence[Mapping[str, Any]], prior: Sequence[Mapping[str, Any]]) -> bool:
    rc, hc = _rate(rule_id, current)
    rp, hp = _rate(rule_id, prior)
    if max(hc, hp) < MIN_HITS:
        return False
    if abs(rc - rp) >= 0.10:
        return True
    return rp > 0 and abs(rc - rp) / rp >= 0.5


def _dominant(rule_id: str, half: Sequence[Mapping[str, Any]], field: str) -> str:
    vals = [
        mix_value(r, field)
        for r in half
        if rule_id in _hits(r) and mix_value(r, field)
    ]
    if len(vals) < MIN_HITS:
        return ""
    return Counter(vals).most_common(1)[0][0]


def _mix_on(rule_id: str, current: Sequence[Mapping[str, Any]], prior: Sequence[Mapping[str, Any]]) -> bool:
    for field in MIX_FIELDS:
        a, b = _dominant(rule_id, current, field), _dominant(rule_id, prior, field)
        if a and b and a != b:
            return True
    return False


def live_rule_slip(
    rows: Sequence[Mapping[str, Any]],
    *,
    by_trace: Mapping[str, str],
    by_entity: Mapping[str, str],
    fp_cap: float,
    parked: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    current, prior, window = split_window(rows)
    empty = {
        "window": window,
        "fp_cap": fp_cap,
        "rules": [],
    }
    if window != "ok":
        return empty
    labeled = []
    for r in list(current) + list(prior):
        y = resolve_y(r, by_trace, by_entity)
        item = dict(r)
        item["y_label"] = y or ""
        labeled.append(item)
    prec = {
        str(x["rule_id"]): x
        for x in (rule_precision_after_labels(labeled).get("rules") or [])
        if x.get("rule_id")
    }
    ids = set()
    for r in list(current) + list(prior):
        ids.update(_hits(r))
    slot = {}
    for p in parked:
        ev = p.get("evidence") if isinstance(p.get("evidence"), Mapping) else {}
        lid = str(ev.get("live_rule_id") or "").strip()
        name = str(p.get("name") or "").strip()
        if lid and name and str(p.get("mode") or "shadow") == "shadow":
            if name.startswith("slip_retire_") or name.startswith("slip_successor_"):
                slot[lid] = name
    out_rules = []
    for rule_id in sorted(ids):
        triggers: list[str] = []
        if _fire_rate_on(rule_id, current, prior):
            triggers.append("fire_rate")
        if _mix_on(rule_id, current, prior):
            triggers.append("mix")
        if not triggers:
            continue
        metrics = prec.get(rule_id) or {}
        h1 = bool(metrics.get("enough_support")) and float(metrics.get("fp_rate") or 0) > fp_cap
        miss_n = 0
        for r in current:
            if resolve_y(r, by_trace, by_entity) == "1" and rule_id not in _hits(r):
                miss_n += 1
        h2 = miss_n >= MIN_MISSES and "mix" in triggers
        if h1 and h2:
            hyp = "ambiguous"
        elif h1:
            hyp = "retire"
        elif h2:
            hyp = "successor"
        else:
            hyp = "underpowered"
        out_rules.append(
            {
                "rule_id": rule_id,
                "triggers": triggers,
                "hypothesis": hyp,
                "fp_rate": metrics.get("fp_rate"),
                "labeled_hits": int(metrics.get("labeled_hits") or 0),
                "miss_count": miss_n,
                "miss_is_not_recall": True,
                "parked_draft": slot.get(rule_id),
                "park_reason": None,
            }
        )
    return {"window": "ok", "fp_cap": fp_cap, "rules": out_rules}


def sanitize_rule_id(rule_id: str) -> str:
    return _SAFE.sub("_", (rule_id or "").strip())[:80] or "rule"


def find_live_rule(rule_id: str, packs: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    want = (rule_id or "").strip()
    for pack in packs:
        if str(pack.get("mode") or "active") not in {"active", ""}:
            continue
        for rule in pack.get("rules") or []:
            if not isinstance(rule, Mapping):
                continue
            if str(rule.get("id") or "").strip() == want:
                when = rule.get("when") if isinstance(rule.get("when"), list) else []
                return {
                    "when": list(when),
                    "pack_file": str(pack.get("_source_file") or ""),
                    "score_delta": rule.get("score_delta"),
                }
    return None


def existing_slip_slot(live_rule_id: str, packs: Sequence[Mapping[str, Any]]) -> str | None:
    want = (live_rule_id or "").strip()
    for p in packs:
        ev = p.get("evidence") if isinstance(p.get("evidence"), Mapping) else {}
        if str(ev.get("live_rule_id") or "").strip() != want:
            continue
        name = str(p.get("name") or "").strip()
        if name.startswith("slip_retire_") or name.startswith("slip_successor_"):
            if str(p.get("mode") or "shadow") == "shadow":
                return name
    return None


def slip_draft_would_clobber(
    name: str,
    evidence: Mapping[str, Any] | None,
    shadow_packs: Sequence[Mapping[str, Any]],
) -> bool:
    n = (name or "").strip()
    if n.startswith("slip_retire_") or n.startswith("slip_successor_"):
        return True
    lid = str((evidence or {}).get("live_rule_id") or "").strip()
    return bool(lid and existing_slip_slot(lid, shadow_packs))


def build_retire_pack(rule_id: str, when: list, *, fp_rate: Any, triggers: list[str]) -> dict[str, Any]:
    safe = sanitize_rule_id(rule_id)
    return {
        "version": 1,
        "name": f"slip_retire_{safe}",
        "mode": "shadow",
        "is_ai_authored": False,
        "authored_by": "slip_critic",
        "rules": [{"id": rule_id, "when": list(when), "score_delta": 5}],
        "evidence": {
            "slip_kind": "retire",
            "live_rule_id": rule_id,
            "fp_rate": fp_rate,
            "triggers": list(triggers),
            "miss_is_not_recall": True,
        },
    }


def build_successor_pack(
    live_rule_id: str,
    field: str,
    value: str,
    *,
    miss_count: int,
    triggers: list[str],
) -> dict[str, Any] | None:
    if field not in LEGAL_WHEN_FIELDS or not str(value).strip():
        return None
    safe = sanitize_rule_id(live_rule_id)
    token = sanitize_rule_id(str(value))[:16]
    new_id = f"slip_{safe}_{token}"[:80]
    return {
        "version": 1,
        "name": f"slip_successor_{safe}",
        "mode": "shadow",
        "is_ai_authored": False,
        "authored_by": "slip_critic",
        "rules": [
            {
                "id": new_id,
                "when": [{"field": field, "op": "eq", "value": value}],
                "score_delta": 15,
            }
        ],
        "evidence": {
            "slip_kind": "successor",
            "live_rule_id": live_rule_id,
            "miss_count": miss_count,
            "mix_field": field,
            "mix_value": value,
            "triggers": list(triggers),
            "miss_is_not_recall": True,
        },
    }


def write_slip_pack(pack: Mapping[str, Any]) -> str:
    kind = str((pack.get("evidence") or {}).get("slip_kind") or "slip")
    safe = sanitize_rule_id(str((pack.get("evidence") or {}).get("live_rule_id") or "rule"))
    path = Path(settings.rules_path)
    path.mkdir(parents=True, exist_ok=True)
    fname = f"slip_{kind}_{safe}.json"
    target = (path / fname).resolve()
    if target.parent != path.resolve() or target.suffix != ".json":
        raise ValueError("slip path outside rules dir")
    if target.exists():
        return fname
    target.write_text(json.dumps(dict(pack), indent=2), encoding="utf-8")
    return fname


def successor_mix(
    current: Sequence[Mapping[str, Any]],
    rule_id: str,
    by_trace: Mapping[str, str],
    by_entity: Mapping[str, str],
) -> tuple[str, str] | None:
    candidates: list[tuple[str, str, int]] = []
    for field in MIX_FIELDS:
        vals = [
            mix_value(r, field)
            for r in current
            if resolve_y(r, by_trace, by_entity) == "1"
            and rule_id not in _hits(r)
            and mix_value(r, field)
        ]
        if len(vals) < MIN_MISSES:
            continue
        value, count = Counter(vals).most_common(1)[0]
        if count >= MIN_MISSES:
            candidates.append((field, value, count))
    if not candidates:
        return None
    field, value, _ = max(candidates, key=lambda item: (item[2], MIX_FIELDS.index(item[0])))
    return field, value


def load_y_maps(tenant_id: str) -> tuple[dict, dict]:
    from decision_api.y_label_store import load_y_labels

    store = load_y_labels(tenant_id)
    return dict(store.get("by_trace") or {}), dict(store.get("by_entity") or {})


async def _load_slip_audit_rows(tenant_id: str, session: Any = None) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from decision_api.models import AuditRecord

    async def _run(sess: Any) -> list[dict[str, Any]]:
        stmt = (
            select(AuditRecord)
            .where(AuditRecord.tenant_id == tenant_id)
            .order_by(AuditRecord.created_at.desc())
            .limit(500)
        )
        result = await sess.execute(stmt)
        records = result.scalars().all()
        return [
            {
                "trace_id": rec.trace_id,
                "tenant_id": rec.tenant_id,
                "entity_id": rec.entity_id,
                "event_type": rec.event_type,
                "decision": rec.decision,
                "score": rec.score,
                "rule_hits": list(rec.rule_hits or []),
                "payload_snapshot": rec.payload_snapshot,
                "created_at": rec.created_at,
            }
            for rec in records
        ]

    if session is not None:
        return await _run(session)
    from decision_api.db import SessionLocal

    async with SessionLocal() as sess:
        return await _run(sess)


async def maybe_park_live_rule_slip(
    tenant_id: str,
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
    session: Any = None,
) -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    if not tid:
        return {"parked": [], "skipped": [{"rule_id": "", "reason": "no_tenant"}]}
    by_trace, by_entity = load_y_maps(tid)
    from decision_api.json_rules import get_active_packs_snapshot, get_shadow_packs, load_rules
    from decision_api.leftover_promote_gate import leftover_caps_for_tenant

    _add, fp_cap, _min = leftover_caps_for_tenant(tid)
    slip_rows = list(rows) if rows is not None else await _load_slip_audit_rows(tid, session)
    slip = live_rule_slip(
        slip_rows, by_trace=by_trace, by_entity=by_entity, fp_cap=fp_cap, parked=get_shadow_packs()
    )
    parked: list[str] = []
    skipped: list[dict[str, str]] = []
    active = get_active_packs_snapshot()
    shadows = get_shadow_packs()
    current, _prior, _win = split_window(slip_rows)
    for row in slip.get("rules") or []:
        rid = str(row.get("rule_id") or "")
        if existing_slip_slot(rid, shadows):
            skipped.append({"rule_id": rid, "reason": "already_parked"})
            continue
        hyp = row.get("hypothesis")
        if hyp not in {"retire", "successor"}:
            skipped.append({"rule_id": rid, "reason": str(hyp)})
            continue
        if hyp == "retire":
            found = find_live_rule(rid, active)
            if not found or not found.get("when"):
                skipped.append({"rule_id": rid, "reason": "no_live_when"})
                continue
            pack = build_retire_pack(
                rid, found["when"], fp_rate=row.get("fp_rate"), triggers=list(row.get("triggers") or [])
            )
        else:
            # ponytail: current half only — full slip_rows would inflate miss counts with prior
            mix = successor_mix(current, rid, by_trace, by_entity)
            if not mix:
                skipped.append({"rule_id": rid, "reason": "no_legal_when"})
                continue
            pack = build_successor_pack(
                rid, mix[0], mix[1], miss_count=int(row.get("miss_count") or 0), triggers=list(row.get("triggers") or [])
            )
            if pack is None:
                skipped.append({"rule_id": rid, "reason": "no_legal_when"})
                continue
        fname = write_slip_pack(pack)
        load_rules()
        from decision_api.rule_api import _append_rule_change

        _append_rule_change(
            "park_live_rule_slip",
            fname,
            actor="slip_critic",
            detail={"live_rule_id": rid, "hypothesis": hyp},
        )
        parked.append(str(pack["name"]))
        shadows = get_shadow_packs()
    return {"parked": parked, "skipped": skipped}
