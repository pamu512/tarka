from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

from decision_api.y_label_store import _HEX64, _data_dir, _tenant_slug

HELPFULNESS_DROP = frozenset({"leftover_extras_fp_over_cap", "leftover_extras_no_lift"})
KILLED_SCHEMA = "tarka.killed_scout_fingerprints/v1"

_lock = threading.Lock()


def brain_wire_verdict(
    helpfulness: Mapping[str, Any] | None,
    precision: Mapping[str, Any] | None,
    *,
    proposed_rule_ids: Sequence[str],
    fp_cap: float,
) -> dict[str, Any]:
    h = helpfulness if isinstance(helpfulness, Mapping) else {}
    blockers = {str(b) for b in (h.get("blockers") or []) if b}
    drop = next(
        (
            b
            for b in ("leftover_extras_fp_over_cap", "leftover_extras_no_lift")
            if b in blockers
        ),
        None,
    )
    if drop:
        return {
            "publish_allowed": False,
            "reason": drop,
            "keep_rule_ids": [],
            "stamp_underpowered": False,
            "should_kill": True,
        }
    keep: list[str] = []
    rules = {
        str(r.get("rule_id") or ""): r
        for r in ((precision or {}).get("rules") or [])
        if isinstance(r, Mapping)
    }
    for rid in proposed_rule_ids:
        token = str(rid or "").strip()
        if not token:
            continue
        row = rules.get(token) or {}
        if bool(row.get("enough_support")) and float(row.get("fp_rate") or 0) > fp_cap:
            continue
        keep.append(token)
    if proposed_rule_ids and not keep:
        return {
            "publish_allowed": False,
            "reason": "rule_fp_over_cap",
            "keep_rule_ids": [],
            "stamp_underpowered": False,
            "should_kill": False,
        }
    return {
        "publish_allowed": True,
        "reason": None,
        "keep_rule_ids": keep,
        "stamp_underpowered": bool(h.get("underpowered")),
        "should_kill": False,
    }


def _file_token(tenant_id: str) -> str:
    slug = _tenant_slug(tenant_id)
    digest = hashlib.sha256(f"tarka.killed_scout:{slug}".encode("utf-8")).hexdigest()
    if not _HEX64.fullmatch(digest):
        raise ValueError("invalid killed scout file token")
    return digest


def killed_path(tenant_id: str) -> Path:
    token = _file_token(tenant_id)
    base = _data_dir()
    target = (base / f"killed_scout_{token}.json").resolve()
    if target.parent != base or target.suffix != ".json":
        raise ValueError("killed scout path outside calibration data dir")
    return target


def _pair(raw: Any) -> tuple[str, str] | None:
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        kind, value = str(raw[0] or "").strip(), str(raw[1] or "").strip()
        if kind and value:
            return (kind, value)
    return None


def load_killed_fingerprints(tenant_id: str) -> set[tuple[str, str]]:
    try:
        path = killed_path(tenant_id)
    except ValueError:
        return set()
    if not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(raw, dict):
        return set()
    out: set[tuple[str, str]] = set()
    for item in raw.get("fingerprints") or []:
        pair = _pair(item)
        if pair:
            out.add(pair)
    return out


def add_killed_fingerprints(tenant_id: str, keys: Sequence[tuple[str, str]]) -> None:
    incoming = [p for k in keys if (p := _pair(k))]
    if not incoming:
        return
    with _lock:
        cur = load_killed_fingerprints(tenant_id)
        cur.update(incoming)
        path = killed_path(tenant_id)
        payload = {
            "schema_id": KILLED_SCHEMA,
            "tenant_id": tenant_id,
            "fingerprints": sorted(cur),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def fingerprint_from_pack(pack: Mapping[str, Any] | None) -> tuple[str, str] | None:
    if not isinstance(pack, Mapping):
        return None
    ev = pack.get("evidence") if isinstance(pack.get("evidence"), Mapping) else {}
    kind = str(ev.get("fingerprint_kind") or "").strip()
    value = str(ev.get("fingerprint_value") or "").strip()
    if kind and value:
        return (kind, value)
    rid = str(pack.get("scout_report_id") or "").strip()
    if rid:
        return ("scout_report_id", rid)
    return None


def disable_ai_shadow_packs(
    helpfulness: Mapping[str, Any] | None,
    *,
    tenant_id: str = "",
) -> list[str]:
    verdict = brain_wire_verdict(
        helpfulness, {"rules": []}, proposed_rule_ids=[], fp_cap=0.4
    )
    if not verdict.get("should_kill"):
        return []
    from decision_api.config import settings
    from decision_api.json_rules import get_shadow_packs, load_rules
    from decision_api.rule_api import _append_rule_change

    base = Path(settings.rules_path)
    by_name = (
        {p.name: p for p in base.glob("*.json") if p.is_file()} if base.is_dir() else {}
    )
    killed: list[str] = []
    keys: list[tuple[str, str]] = []
    for pack in get_shadow_packs():
        if pack.get("mode") != "shadow" or pack.get("is_ai_authored") is not True:
            continue
        if str(pack.get("authored_by") or "") == "slip_critic":
            continue
        fname = str(pack.get("_source_file") or "").strip()
        fpath = by_name.get(fname)
        if fpath is None:
            continue
        try:
            on_disk = json.loads(fpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(on_disk, dict):
            continue
        if on_disk.get("mode") != "shadow" or on_disk.get("is_ai_authored") is not True:
            continue
        if str(on_disk.get("authored_by") or "") == "slip_critic":
            continue
        on_disk["mode"] = "disabled"
        fpath.write_text(json.dumps(on_disk, indent=2), encoding="utf-8")
        _append_rule_change(
            "kill_shadow_pack_leftover_fp",
            fname,
            detail={
                "helpfulness": dict(helpfulness)
                if isinstance(helpfulness, Mapping)
                else {}
            },
        )
        fp = fingerprint_from_pack(on_disk) or fingerprint_from_pack(pack)
        if fp:
            keys.append(fp)
        killed.append(fname)
    if tenant_id and keys:
        add_killed_fingerprints(tenant_id, keys)
    load_rules()
    return killed


async def maybe_kill_leftover_fp_shadows(
    tenant_id: str,
    leftover_g: Mapping[str, Any] | None = None,
) -> list[str]:
    tid = (tenant_id or "").strip()
    gate: Mapping[str, Any] = leftover_g if isinstance(leftover_g, Mapping) else {}
    if leftover_g is None:
        from decision_api.db import SessionLocal
        from decision_api.leftover_promote_gate import compute_desk_and_leftover_gates

        async with SessionLocal() as session:
            gates = await compute_desk_and_leftover_gates(tid, None, session=session)
        raw = gates.get("leftover_promote_gate")
        gate = raw if isinstance(raw, Mapping) else {}
    h = gate.get("helpfulness")
    if not isinstance(h, Mapping):
        h = gate
    return disable_ai_shadow_packs(h, tenant_id=tid)
