"""Observe-only pack canary on evaluate (issue #150 slice 1).

A configured fraction of traffic (or ``x-tarka-pack-canary: 1``) evaluates a
**candidate** JSON pack through the same decision-api / Rust JSON engine. The
live pack remains the sole allow/deny source. Results are recorded on the
existing audit snapshot and shadow observation log.

This is not Flagger/Argo and does not promote the candidate verdict.
``PACK_CANARY_PERCENT`` default 0 = off. Percent > 0 with a missing candidate
fail-closes evaluate instead of silently scoring live-only while claiming canary.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from decision_api.config import settings

log = logging.getLogger("decision-api.pack_canary")

PACK_CANARY_HEADER = "x-tarka-pack-canary"
_FAIL_CLOSED_STATUS = 503


def configured_percent() -> float:
    try:
        pct = float(getattr(settings, "pack_canary_percent", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, pct))


def configured_pack_id() -> str:
    return str(getattr(settings, "pack_canary_pack_id", "") or "").strip()


def configured_pack_path() -> str:
    return str(getattr(settings, "pack_canary_path", "") or "").strip()


def header_forces_candidate(request: Request) -> bool:
    raw = (request.headers.get(PACK_CANARY_HEADER) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def canary_requested(request: Request) -> bool:
    return configured_percent() > 0.0 or header_forces_candidate(request)


def _load_pack_file(path: str) -> dict[str, Any] | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        pack = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("pack_canary_read_failed path=%s err=%s", path, exc)
        return None
    if not isinstance(pack, dict):
        return None
    out = dict(pack)
    out.setdefault("_source_file", p.name)
    return out


def _pack_matches(pack: dict[str, Any], pack_id: str) -> bool:
    src = str(pack.get("_source_file") or "")
    names = {
        str(pack.get("id") or "").strip(),
        str(pack.get("name") or "").strip(),
        src,
        Path(src).name,
        Path(src).stem,
    }
    names.discard("")
    return pack_id in names


def resolve_candidate_packs() -> list[dict[str, Any]]:
    """Resolve the candidate pack from ``PACK_CANARY_PATH`` or ``PACK_CANARY_PACK_ID``."""
    path = configured_pack_path()
    if path:
        loaded = _load_pack_file(path)
        return [loaded] if loaded is not None else []

    pack_id = configured_pack_id()
    if not pack_id:
        return []

    if pack_id.endswith(".json") or "/" in pack_id or "\\" in pack_id:
        for candidate in (pack_id, str(Path(settings.rules_path) / pack_id)):
            loaded = _load_pack_file(candidate)
            if loaded is not None:
                return [loaded]

    from decision_api.json_rules import get_active_packs_snapshot, get_shadow_packs

    for pack in list(get_active_packs_snapshot()) + list(get_shadow_packs()):
        if isinstance(pack, dict) and _pack_matches(pack, pack_id):
            return [dict(pack)]

    rules_dir = Path(settings.rules_path)
    if rules_dir.is_dir():
        for f in sorted(rules_dir.glob("*.json")):
            if f.name == pack_id or f.stem == pack_id or f.name == f"{pack_id}.json":
                loaded = _load_pack_file(str(f))
                return [loaded] if loaded is not None else []
            loaded = _load_pack_file(str(f))
            if loaded is not None and _pack_matches(loaded, pack_id):
                return [loaded]
    return []


def _fail_closed() -> None:
    raise HTTPException(
        status_code=_FAIL_CLOSED_STATUS,
        detail={
            "error": "pack_canary_candidate_missing",
            "message": (
                "Pack canary is requested (PACK_CANARY_PERCENT>0 or "
                "x-tarka-pack-canary) but PACK_CANARY_PACK_ID / PACK_CANARY_PATH "
                "did not resolve to a loadable candidate pack. Fail-closed; "
                "evaluate will not silently score live-only while claiming canary."
            ),
        },
    )


def ensure_pack_canary_ready(request: Request) -> None:
    """Fail-closed when canary is claimed but the candidate pack is missing."""
    if not canary_requested(request):
        return
    if not resolve_candidate_packs():
        _fail_closed()


def _in_percent_sample(
    tenant_id: str, entity_id: str, pack_key: str, percent: float
) -> bool:
    if percent >= 100.0:
        return True
    if percent <= 0.0:
        return False
    from decision_api.json_rules import _pack_experiment_bucket

    bucket = _pack_experiment_bucket(tenant_id, entity_id, f"pack_canary:{pack_key}")
    return bucket < percent


def _evaluate_candidate(
    packs: list[dict[str, Any]],
    *,
    features: dict[str, Any],
    redis_tag_list: list[str],
    tenant_id: str,
    entity_id: str,
    signal_tags: list[str],
) -> dict[str, Any]:
    from decision_api.json_rules import evaluate_adhoc_packs_json
    from decision_api.policy_routing import decision_from_rule_score
    from decision_api.rust_rule_engine_exceptions import (
        RustRuleEngineCircuitOpenError,
        RustRuleEngineInvocationFailed,
    )

    try:
        hits, tags, delta, pack_files = evaluate_adhoc_packs_json(
            packs,
            features,
            redis_tag_list,
            tenant_id,
            entity_id,
            evaluation_mode="simulation",
            record_telemetry=False,
            signal_tags=signal_tags,
        )
    except (RustRuleEngineCircuitOpenError, RustRuleEngineInvocationFailed) as exc:
        log.warning("pack_canary_candidate_eval_failed err=%s", type(exc).__name__)
        return {
            "observe_only": True,
            "mode": "shadow",
            "flagger": False,
            "candidate_eval_failed": True,
            "error": type(exc).__name__,
            "live_verdict_source": "live_pack",
        }

    score = max(0.0, min(100.0, 10.0 + float(delta)))
    return {
        "observe_only": True,
        "mode": "shadow",
        "flagger": False,
        "candidate_decision": decision_from_rule_score(score),
        "candidate_score": score,
        "candidate_rule_hits": hits,
        "candidate_tags": tags,
        "candidate_score_delta": delta,
        "candidate_pack_files": pack_files,
        "live_verdict_source": "live_pack",
    }


def maybe_observe_candidate_pack(
    request: Request,
    *,
    features: dict[str, Any],
    redis_tag_list: list[str],
    tenant_id: str,
    entity_id: str,
    signal_tags: list[str] | None = None,
) -> dict[str, Any] | None:
    """Evaluate the candidate pack when sampled or forced. Live verdict is unchanged.

    Returns ``None`` when canary is off or this request is outside the percent
    sample. Raises 503 when canary is claimed and the candidate pack is missing.
    """
    forced = header_forces_candidate(request)
    percent = configured_percent()
    if not forced and percent <= 0.0:
        return None

    packs = resolve_candidate_packs()
    if not packs:
        _fail_closed()

    pack_key = (
        configured_pack_id()
        or configured_pack_path()
        or str(packs[0].get("_source_file") or packs[0].get("name") or "candidate")
    )
    sampled = False
    if not forced:
        if not _in_percent_sample(tenant_id, entity_id, pack_key, percent):
            return None
        sampled = True

    result = _evaluate_candidate(
        packs,
        features=features,
        redis_tag_list=redis_tag_list,
        tenant_id=tenant_id,
        entity_id=entity_id,
        signal_tags=signal_tags or [],
    )
    result["sampled"] = sampled
    result["forced"] = forced
    result["percent"] = percent
    result["pack_id"] = configured_pack_id() or pack_key
    if configured_pack_path():
        result["pack_path"] = configured_pack_path()
    return result
