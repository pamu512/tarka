"""Pure loyalty economics multi-gate engine (dispatch / redeem / order).

Gate policy v1 defaults (same outcome across gates unless extended via ``gate_policies``):
- VIP allowlist → all gates eligible, reason ``vip_allowlist``.
- New-member grace → all eligible, reason ``new_member_grace``.
- ``loyalty_ltv_ratio > ineligible_above_ratio`` (scaled by per-gate ``ratio_weight``) →
  ineligible, reason ``loyalty_ltv_above_threshold``.
- ``loyalty_ltv_ratio <= restore_at_or_below_ratio`` → eligible only after dwell in restore band.
- Between thresholds → keep prior ineligibility when ``prior_gate_state.ineligible_since`` set.
- Per-gate ``churn_flips``: when true, churn proxy + ratio > ``target_loyalty_ltv_ratio`` may
  flip ineligible even below ``ineligible_above_ratio`` (dispatch vs order independence).

Never sets ``eligible: true`` on missing/incomplete/stale/config_missing feeds.
``policy.order_decision_untouched`` is always ``True`` — this path does not deny orders.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA_ID = "tarka.loyalty_economics_gates/v1"

_GATE_NAMES = ("dispatch", "redeem", "order")

_REQUIRED_CONFIG_KEYS = (
    "program_id",
    "config_version",
    "effective_at",
    "acquisition_cost_minor",
    "retention_cost_minor",
    "target_loyalty_ltv_ratio",
    "ineligible_above_ratio",
    "restore_at_or_below_ratio",
    "min_dwell_seconds",
    "window",
    "velocity_window",
    "new_member_grace_days",
    "vip_entity_ids",
    "max_feed_age_seconds",
)

_FEED_LIST_KEYS = ("orders", "loyalty_ledger", "lifecycle")


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_trailing_days(window: str, default: int = 7) -> int:
    if not isinstance(window, str):
        return default
    m = re.match(r"^trailing_(\d+)d$", window.strip())
    if not m:
        return default
    try:
        return max(1, int(m.group(1)))
    except ValueError:
        return default


def _null_gates(status: str, as_of: str | None = None) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "eligible": None,
            "status": status,
            "reasons": [],
            "as_of": as_of,
        }
        for name in _GATE_NAMES
    }


def _gate(
    *,
    eligible: bool | None,
    status: str,
    reasons: list[str],
    as_of: str | None,
) -> dict[str, Any]:
    return {
        "eligible": eligible,
        "status": status,
        "reasons": reasons,
        "as_of": as_of,
    }


def _entity_ids(entity_id: str, cluster_entity_ids: list[str] | None) -> set[str]:
    if cluster_entity_ids and len(cluster_entity_ids) >= 2:
        return {str(x) for x in cluster_entity_ids}
    return {entity_id}


def _validate_config(program_config: dict | None) -> tuple[dict | None, str | None]:
    if not isinstance(program_config, dict):
        return None, "config_missing"
    for key in _REQUIRED_CONFIG_KEYS:
        if key not in program_config:
            return None, "config_missing"
    return program_config, None


def _validate_feeds(feed_snapshot: dict | None) -> tuple[dict | None, str | None]:
    if feed_snapshot is None:
        return None, "feeds_missing"
    if not isinstance(feed_snapshot, dict):
        return None, "feeds_missing"
    if "refunds" not in feed_snapshot:
        return None, "feeds_incomplete"
    for key in _FEED_LIST_KEYS:
        if key not in feed_snapshot:
            return None, "feeds_incomplete"
        val = feed_snapshot[key]
        if not isinstance(val, list) or len(val) == 0:
            return None, "feeds_incomplete"
    return feed_snapshot, None


def _check_stale(
    feed_snapshot: dict,
    max_feed_age_seconds: int,
    now: datetime,
) -> bool:
    as_of = _parse_iso(feed_snapshot.get("as_of"))
    if as_of is None:
        return True
    age = (now - as_of).total_seconds()
    return age > max_feed_age_seconds


def _rollup_ltv(
    feed_snapshot: dict,
    ids: set[str],
) -> int:
    total = 0
    for row in feed_snapshot.get("orders") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("entity_id")) not in ids:
            continue
        if str(row.get("status", "")).lower() != "paid":
            continue
        try:
            total += int(row.get("amount_minor") or 0)
        except (TypeError, ValueError):
            continue
    for row in feed_snapshot.get("refunds") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("entity_id")) not in ids:
            continue
        try:
            total -= int(row.get("amount_minor") or 0)
        except (TypeError, ValueError):
            continue
    return max(0, total)


def _rollup_loyalty_cost(feed_snapshot: dict, ids: set[str]) -> int:
    total = 0
    for row in feed_snapshot.get("loyalty_ledger") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("entity_id")) not in ids:
            continue
        try:
            total += int(row.get("value_minor") or 0)
        except (TypeError, ValueError):
            continue
    return max(0, total)


def _order_velocity(
    feed_snapshot: dict,
    ids: set[str],
    velocity_window: str,
    now: datetime,
) -> int:
    days = _parse_trailing_days(velocity_window, default=7)
    cutoff = now - timedelta(days=days)
    count = 0
    for row in feed_snapshot.get("orders") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("entity_id")) not in ids:
            continue
        ts = _parse_iso(row.get("ts"))
        if ts is None or ts < cutoff:
            continue
        count += 1
    return count


def _churn_proxy(
    feed_snapshot: dict,
    entity_id: str,
    order_count: int,
    now: datetime,
) -> bool:
    created_at: datetime | None = None
    for row in feed_snapshot.get("lifecycle") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("entity_id")) != entity_id:
            continue
        created_at = _parse_iso(row.get("created_at"))
        break
    if created_at is None:
        return False
    age_days = (now - created_at).total_seconds() / 86400.0
    return age_days <= 30 and order_count <= 1


def _in_new_member_grace(
    feed_snapshot: dict,
    entity_id: str,
    grace_days: int,
    now: datetime,
) -> bool:
    if grace_days <= 0:
        return False
    for row in feed_snapshot.get("lifecycle") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("entity_id")) != entity_id:
            continue
        created_at = _parse_iso(row.get("created_at"))
        if created_at is None:
            return False
        age_days = (now - created_at).total_seconds() / 86400.0
        return age_days <= grace_days
    return False


def _dwell_seconds(since_iso: str | None, now: datetime) -> float:
    since = _parse_iso(since_iso)
    if since is None:
        return 0.0
    return max(0.0, (now - since).total_seconds())


def _resolve_gate_policy(cfg: dict, gate_name: str) -> dict[str, float | bool]:
    policies = cfg.get("gate_policies")
    raw: dict[str, Any] = {}
    if isinstance(policies, dict):
        gate_raw = policies.get(gate_name)
        if isinstance(gate_raw, dict):
            raw = gate_raw
    try:
        ratio_weight = float(raw.get("ratio_weight", 1.0))
    except (TypeError, ValueError):
        ratio_weight = 1.0
    if ratio_weight <= 0:
        ratio_weight = 1.0
    return {
        "ratio_weight": ratio_weight,
        "churn_flips": bool(raw.get("churn_flips", False)),
    }


def _base_gate_eligibility(
    *,
    ratio: float,
    ineligible_above: float,
    restore_at_or_below: float,
    min_dwell: int,
    prior_ineligible: bool,
    restore_since: str | None,
    now: datetime,
    reasons_base: list[str],
    is_vip: bool,
    in_grace: bool,
) -> tuple[bool, list[str]]:
    if is_vip:
        return True, ["vip_allowlist"]
    if in_grace:
        return True, ["new_member_grace"]
    if ratio > ineligible_above:
        return False, reasons_base + ["loyalty_ltv_above_threshold"]
    if ratio <= restore_at_or_below:
        if not prior_ineligible:
            return True, list(reasons_base)
        dwell = _dwell_seconds(restore_since, now)
        if dwell >= min_dwell:
            return True, list(reasons_base)
        return False, reasons_base + ["dwell_not_met"]
    if prior_ineligible:
        return False, reasons_base + ["hysteresis_band_prior_ineligible"]
    return True, list(reasons_base)


def _evaluate_gate(
    *,
    gate_name: str,
    cfg: dict,
    ratio: float,
    ineligible_above: float,
    restore_at_or_below: float,
    target_ratio: float,
    min_dwell: int,
    prior_ineligible: bool,
    restore_since: str | None,
    now: datetime,
    reasons_base: list[str],
    is_vip: bool,
    in_grace: bool,
    churn: bool,
) -> tuple[bool, list[str]]:
    policy = _resolve_gate_policy(cfg, gate_name)
    effective_ineligible = ineligible_above / float(policy["ratio_weight"])
    eligible, gate_reasons = _base_gate_eligibility(
        ratio=ratio,
        ineligible_above=effective_ineligible,
        restore_at_or_below=restore_at_or_below,
        min_dwell=min_dwell,
        prior_ineligible=prior_ineligible,
        restore_since=restore_since,
        now=now,
        reasons_base=reasons_base,
        is_vip=is_vip,
        in_grace=in_grace,
    )
    if (
        eligible
        and policy["churn_flips"]
        and churn
        and ratio > target_ratio
    ):
        eligible = False
        gate_reasons = list(gate_reasons) + ["churn_proxy_above_target"]
    return eligible, gate_reasons


def evaluate_loyalty_economics(
    *,
    entity_id: str,
    feed_snapshot: dict | None,
    program_config: dict | None,
    cluster_entity_ids: list[str] | None = None,
    scope: dict | None = None,
    now: datetime | None = None,
    prior_gate_state: dict | None = None,
) -> dict:
    """Evaluate loyalty economics gates for dispatch, redeem, and order."""
    now = now or datetime.now(timezone.utc)
    as_of_str = None
    if isinstance(feed_snapshot, dict):
        raw_as_of = feed_snapshot.get("as_of")
        as_of_str = str(raw_as_of) if raw_as_of else None

    unit = "cluster" if cluster_entity_ids and len(cluster_entity_ids) >= 2 else "entity"
    base: dict[str, Any] = {
        "schema_id": SCHEMA_ID,
        "entity_id": entity_id,
        "unit": unit,
        "scope": scope if isinstance(scope, dict) else None,
        "as_of": as_of_str,
        "policy": {
            "order_decision_untouched": True,
        },
    }

    cfg, cfg_status = _validate_config(program_config)
    if cfg_status:
        base["status"] = cfg_status
        base["gates"] = _null_gates(cfg_status, as_of_str)
        return base

    feeds, feed_status = _validate_feeds(feed_snapshot)
    if feed_status:
        base["status"] = feed_status
        base["gates"] = _null_gates(feed_status, as_of_str)
        return base

    assert cfg is not None and feeds is not None

    try:
        max_age = int(cfg["max_feed_age_seconds"])
    except (TypeError, ValueError):
        max_age = 86400

    if _check_stale(feeds, max_age, now):
        base["status"] = "stale"
        base["gates"] = _null_gates("stale", as_of_str)
        return base

    ids = _entity_ids(entity_id, cluster_entity_ids)
    ltv_minor = _rollup_ltv(feeds, ids)
    loyalty_cost_minor = _rollup_loyalty_cost(feeds, ids)

    if ltv_minor > 0:
        ratio = loyalty_cost_minor / ltv_minor
    elif loyalty_cost_minor > 0:
        ratio = float("inf")
    else:
        ratio = 0.0

    order_count = len(
        [
            r
            for r in feeds.get("orders") or []
            if isinstance(r, dict) and str(r.get("entity_id")) in ids
        ]
    )
    velocity = _order_velocity(feeds, ids, str(cfg.get("velocity_window", "trailing_7d")), now)
    churn = _churn_proxy(feeds, entity_id, order_count, now)

    try:
        ineligible_above = float(cfg["ineligible_above_ratio"])
        restore_at_or_below = float(cfg["restore_at_or_below_ratio"])
        target_ratio = float(cfg["target_loyalty_ltv_ratio"])
        min_dwell = int(cfg["min_dwell_seconds"])
        grace_days = int(cfg["new_member_grace_days"])
    except (TypeError, ValueError):
        base["status"] = "config_missing"
        base["gates"] = _null_gates("config_missing", as_of_str)
        return base

    vip_ids = cfg.get("vip_entity_ids") or []
    is_vip = entity_id in [str(v) for v in vip_ids]
    in_grace = _in_new_member_grace(feeds, entity_id, grace_days, now)

    prior = prior_gate_state if isinstance(prior_gate_state, dict) else {}
    prior_ineligible = bool(prior.get("ineligible_since"))
    restore_since = prior.get("restore_band_since")

    reasons_base: list[str] = []
    if churn:
        reasons_base.append("churn_proxy_new_low_repeat")

    has_spend = "spend" in feeds and isinstance(feeds.get("spend"), list)
    top_status = "ok" if has_spend else "partial_derived"

    base["status"] = top_status
    base["metrics"] = {
        "order_velocity": {"count": velocity, "window": str(cfg.get("velocity_window", "trailing_7d"))},
        "churn_proxy": {"flagged": churn},
        "ltv_minor": ltv_minor,
        "loyalty_cost_minor": loyalty_cost_minor,
        "loyalty_ltv_ratio": ratio if ratio != float("inf") else None,
        "program_roi": None,
        "window": str(cfg.get("window", "trailing_90d")),
    }
    gate_as_of = as_of_str or _iso(now)
    gates = {}
    for name in _GATE_NAMES:
        eligible, gate_reasons = _evaluate_gate(
            gate_name=name,
            cfg=cfg,
            ratio=ratio,
            ineligible_above=ineligible_above,
            restore_at_or_below=restore_at_or_below,
            target_ratio=target_ratio,
            min_dwell=min_dwell,
            prior_ineligible=prior_ineligible,
            restore_since=restore_since,
            now=now,
            reasons_base=reasons_base,
            is_vip=is_vip,
            in_grace=in_grace,
            churn=churn,
        )
        gates[name] = _gate(
            eligible=eligible,
            status="ok",
            reasons=gate_reasons,
            as_of=gate_as_of,
        )
    base["gates"] = gates
    base["policy"]["config_version"] = str(cfg.get("config_version", ""))
    base["policy"]["hysteresis"] = {
        "ineligible_since": prior.get("ineligible_since"),
        "restore_band_since": prior.get("restore_band_since"),
    }
    return base
