"""Thin closed-loop scoreboard numbers. No CRM."""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from typing import Any

SCHEMA_ID = "tarka.loop_metrics/v1"
PACK_METRICS_SCHEMA_ID = "tarka.pack_metrics/v1"
PACK_METRICS_WINDOW = "7d"


def _counter_path() -> Any:
    from pathlib import Path

    from decision_api.config import settings

    return Path(settings.rules_path) / "_loop" / "ai_gate.json"


def load_ai_gate_counts() -> tuple[int, int]:
    path = _counter_path()
    if not path.is_file():
        return 0, 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, 0
    if not isinstance(raw, dict):
        return 0, 0
    try:
        return int(raw.get("blocked") or 0), int(raw.get("passed") or 0)
    except (TypeError, ValueError):
        return 0, 0


def record_ai_gate(*, blocked: bool) -> None:
    blocked_n, passed_n = load_ai_gate_counts()
    if blocked:
        blocked_n += 1
    else:
        passed_n += 1
    path = _counter_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"blocked": blocked_n, "passed": passed_n}),
        encoding="utf-8",
    )


def _parse_ts(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _ms(start: Any, end: Any) -> float | None:
    a = _parse_ts(start)
    b = _parse_ts(end)
    if a is None or b is None:
        return None
    return max(0.0, (b - a).total_seconds() * 1000.0)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return float(statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1])


def _fp_amount(raw: Any) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return 0.0
    try:
        blob = json.loads(text)
    except json.JSONDecodeError:
        try:
            return float(text)
        except ValueError:
            return 0.0
    if isinstance(blob, (int, float)):
        return float(blob)
    if isinstance(blob, dict):
        try:
            return float(blob.get("amount") or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _pack_id(pack: dict[str, Any]) -> str:
    return str(pack.get("name") or pack.get("pack_id") or "").strip()


def _hits(row: dict[str, Any]) -> bool:
    hits = row.get("shadow_rule_hits")
    if hits is None:
        hits = row.get("rule_hits")
    return bool(hits)


def compute_pack_metrics(
    packs: list[dict[str, Any]],
    observations: list[dict[str, Any]] | None = None,
    *,
    tenant_id: str = "",
) -> list[dict[str, Any]]:
    """Per-pack hit rate / divergence. null = unknown. Empty tenant → []."""
    want = (tenant_id or "").strip()
    if not want:
        return []
    rows = observations if isinstance(observations, list) else []
    by_pack: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_tenant = str(row.get("tenant_id") or "").strip()
        if row_tenant and row_tenant != want:
            continue
        pid = str(row.get("pack_id") or "").strip()
        if pid:
            by_pack.setdefault(pid, []).append(row)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    as_of = datetime.now().astimezone().isoformat()
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        pack_tenant = str(pack.get("tenant_id") or "").strip()
        if pack_tenant and pack_tenant != want:
            continue
        pid = _pack_id(pack)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        sample = by_pack.get(pid) or []
        if not sample:
            out.append(
                {
                    "schema_id": PACK_METRICS_SCHEMA_ID,
                    "pack_id": pid,
                    "rule_hit_rate": None,
                    "shadow_divergence": None,
                    "window": PACK_METRICS_WINDOW,
                    "as_of": None,
                }
            )
            continue
        n = len(sample)
        out.append(
            {
                "schema_id": PACK_METRICS_SCHEMA_ID,
                "pack_id": pid,
                "rule_hit_rate": sum(1 for r in sample if _hits(r)) / n,
                "shadow_divergence": sum(1 for r in sample if r.get("diverged")) / n,
                "window": PACK_METRICS_WINDOW,
                "as_of": as_of,
            }
        )
    return out


def _receipt_tokens(row: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("evaluation_token", "trace_id"):
        token = str(row.get(key) or "").strip()
        if token and token not in out:
            out.append(token)
    return out


def _horizon_windows() -> dict[str, int]:
    from decision_api.label_horizon import horizon_policy

    raw = horizon_policy().get("by_kind")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for kind, row in raw.items():
        days = row.get("window_days") if isinstance(row, dict) else row
        try:
            n = int(days)
        except (TypeError, ValueError):
            continue
        if n >= 1:
            out[str(kind).strip().lower()] = n
    return out


def _in_horizon(
    kind: str,
    decided: datetime | None,
    labeled: datetime | None,
    windows: dict[str, int],
) -> bool:
    if decided is None or labeled is None:
        return False
    days = windows.get(str(kind or "").strip().lower())
    if days is None:
        return False
    lag = (labeled - decided).total_seconds()
    return 0 <= lag <= days * 86400.0


def _join_rate_unknown(reason: str) -> dict[str, Any]:
    return {
        "join_rate": None,
        "labeled_receipt_rate": None,
        "labeled_receipt_count": None,
        "receipt_count": None,
        "unknown_reasons": {
            "join_rate": reason,
            "labeled_receipt_rate": reason,
        },
    }


def _join_rate_fields(
    labels: dict[str, Any],
    receipts: list[dict[str, Any]] | None,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    """In-horizon labeled/receipts. null = unknown. Never 0.0 theater."""
    want = (tenant_id or "").strip()
    if not want:
        return _join_rate_unknown("empty_tenant")
    if receipts is None:
        return _join_rate_unknown("receipt_store_absent")
    kinds = labels.get("label_kind_by_trace") if isinstance(labels, dict) else {}
    kinds = kinds if isinstance(kinds, dict) else {}
    labeled_at = labels.get("labeled_at_by_trace") if isinstance(labels, dict) else {}
    labeled_at = labeled_at if isinstance(labeled_at, dict) else {}
    decided_at = labels.get("decided_at_by_trace") if isinstance(labels, dict) else {}
    decided_at = decided_at if isinstance(decided_at, dict) else {}
    windows = _horizon_windows()
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for row in receipts:
        if not isinstance(row, dict):
            continue
        row_tenant = str(row.get("tenant_id") or "").strip()
        if row_tenant and row_tenant != want:
            continue
        tokens = _receipt_tokens(row)
        if not tokens or tokens[0] in seen:
            continue
        seen.add(tokens[0])
        rows.append(row)
    if not rows:
        return _join_rate_unknown("no_receipts")
    if not kinds:
        return _join_rate_unknown("no_labels")
    labeled_n = 0
    for row in rows:
        matched = ""
        kind = ""
        for token in _receipt_tokens(row):
            raw = kinds.get(token)
            if raw is None:
                continue
            matched = token
            kind = str(raw).strip().lower()
            break
        if not matched or not kind:
            continue
        decided = (
            _parse_ts(decided_at.get(matched))
            or _parse_ts(row.get("decided_at"))
            or _parse_ts(row.get("created_at"))
        )
        labeled = _parse_ts(labeled_at.get(matched))
        if _in_horizon(kind, decided, labeled, windows):
            labeled_n += 1
    n = len(rows)
    rate = labeled_n / n
    return {
        "join_rate": rate,
        "labeled_receipt_rate": rate,
        "labeled_receipt_count": labeled_n,
        "receipt_count": n,
        "unknown_reasons": {},
    }


def compute_loop_metrics(
    packs: list[dict[str, Any]],
    labels: dict[str, Any],
    *,
    ai_blocked: int = 0,
    ai_passed: int = 0,
    tenant_id: str = "",
    observations: list[dict[str, Any]] | None = None,
    receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    human_n = 0
    ai_n = 0
    leftover_n = 0
    leftover_ms: list[float] = []
    promote_ms: list[float] = []
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        life = pack.get("lifecycle") if isinstance(pack.get("lifecycle"), dict) else {}
        state = str(life.get("state") or "")
        ai = bool(pack.get("is_ai_authored"))
        if state in {"observe", "promoted"}:
            if str(pack.get("source_key") or "").startswith("leftover:"):
                leftover_n += 1
            if ai:
                ai_n += 1
            else:
                human_n += 1
        created = life.get("created_at")
        observed = life.get("observe_entered_at")
        delta = _ms(created, observed)
        if delta is not None and (pack.get("source_key") or "").startswith("leftover:"):
            leftover_ms.append(delta)
        if state == "promoted":
            ttl = _ms(observed or created, life.get("promoted_at"))
            if ttl is not None:
                promote_ms.append(ttl)

    kinds = labels.get("label_kind_by_trace") if isinstance(labels, dict) else {}
    kinds = kinds if isinstance(kinds, dict) else {}
    costs = labels.get("fp_cost_by_trace") if isinstance(labels, dict) else {}
    costs = costs if isinstance(costs, dict) else {}
    labeled_at = labels.get("labeled_at_by_trace") if isinstance(labels, dict) else {}
    labeled_at = labeled_at if isinstance(labeled_at, dict) else {}
    decided_at = labels.get("decided_at_by_trace") if isinstance(labels, dict) else {}
    decided_at = decided_at if isinstance(decided_at, dict) else {}

    fp_keys = [k for k, v in kinds.items() if str(v).strip().lower() == "fp"]
    fp_cost_sum = sum(_fp_amount(costs.get(k)) for k in fp_keys)
    label_ms = [
        m
        for k in kinds
        for m in [_ms(decided_at.get(k), labeled_at.get(k))]
        if m is not None
    ]

    blocked = max(0, int(ai_blocked))
    passed = max(0, int(ai_passed))
    denom = blocked + passed
    demote_propose = 0
    demote_confirm = 0
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        demote = (pack.get("lifecycle") or {}).get("demote")
        if isinstance(demote, dict):
            state = str(demote.get("state") or "")
            if state == "proposed":
                demote_propose += 1
            if state == "confirmed":
                demote_confirm += 1
    observe_n = human_n + ai_n
    label_p50 = _percentile(label_ms, 50)
    promote_p50 = _percentile(promote_ms, 50)
    return {
        "schema_id": SCHEMA_ID,
        "leftover_to_draft_ms": {
            "p50": _percentile(leftover_ms, 50),
            "p95": _percentile(leftover_ms, 95),
        },
        "drafts_to_observe": {"human": human_n, "ai": ai_n},
        "leftover_mint_rate": (leftover_n / observe_n) if observe_n else None,
        "ai_backtest_block_rate": (blocked / denom) if denom else None,
        "fp_count": len(fp_keys),
        "fp_cost_sum": fp_cost_sum,
        "label_latency_ms": {
            "p50": label_p50,
            "p95": _percentile(label_ms, 95),
        },
        "label_latency_hours": {
            "p50": (label_p50 / 3_600_000.0) if label_p50 is not None else None,
            "p95": None
            if _percentile(label_ms, 95) is None
            else _percentile(label_ms, 95) / 3_600_000.0,
        },
        "promote_ttl_ms": {
            "p50": promote_p50,
            "p95": _percentile(promote_ms, 95),
        },
        "promote_ttl_hours": {
            "p50": (promote_p50 / 3_600_000.0) if promote_p50 is not None else None,
            "p95": None
            if _percentile(promote_ms, 95) is None
            else _percentile(promote_ms, 95) / 3_600_000.0,
        },
        "demote_propose_count": demote_propose,
        "demote_confirm_count": demote_confirm,
        "evaluate_count": None,
        "action_mix": None,
        "rule_hit_rate": None,
        "shadow_divergence": None,
        "pack_metrics": compute_pack_metrics(packs, observations, tenant_id=tenant_id),
        **_join_rate_fields(labels, receipts, tenant_id=tenant_id),
    }
