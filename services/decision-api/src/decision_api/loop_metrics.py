"""Thin closed-loop scoreboard numbers. No CRM.

GLOBAL evaluate_count / action_mix / shadow_divergence fill from audit/receipts
and shadow pairs when present. null = unknown. share-with-M3; do-not-double-implement.
"""

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


def _action_token(row: dict[str, Any]) -> str:
    raw = row.get("action") or row.get("enforcement_action") or row.get("decision")
    return str(raw or "").strip().lower()


def _is_shadow_pair(row: dict[str, Any]) -> bool:
    if "diverged" in row:
        return True
    prod = str(row.get("production_decision") or "").strip()
    shadow = str(row.get("shadow_decision") or "").strip()
    return bool(prod and shadow)


def _with_diverged(row: dict[str, Any]) -> dict[str, Any]:
    if "diverged" in row:
        return row
    prod = str(row.get("production_decision") or "").strip()
    shadow = str(row.get("shadow_decision") or "").strip()
    if prod and shadow:
        return {**row, "diverged": prod != shadow}
    return row


def shadow_divergence_rate(rows: list[dict[str, Any]] | None) -> float | None:
    """M3 pack math: diverged / n. None when no paired rows (not 0.0 theater)."""
    sample = [r for r in (rows or []) if isinstance(r, dict)]
    if not sample:
        return None
    return sum(1 for r in sample if r.get("diverged")) / len(sample)


def _tenant_rows(
    rows: list[dict[str, Any]] | None, tenant_id: str
) -> list[dict[str, Any]]:
    want = (tenant_id or "").strip()
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        row_tenant = str(row.get("tenant_id") or "").strip()
        if row_tenant and row_tenant != want:
            continue
        out.append(row)
    return out


def _global_observation_rows(
    observations: list[dict[str, Any]] | None,
    tenant_id: str,
    evaluations: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Tenant-tagged rows, or unscoped rows paired to this tenant's evaluate traces."""
    want = (tenant_id or "").strip()
    traces = {
        str(row.get("trace_id") or row.get("evaluation_token") or "").strip()
        for row in (evaluations or [])
        if isinstance(row, dict)
    }
    traces.discard("")
    out: list[dict[str, Any]] = []
    for row in observations or []:
        if not isinstance(row, dict):
            continue
        row_tenant = str(row.get("tenant_id") or "").strip()
        if row_tenant:
            if row_tenant == want:
                out.append(row)
            continue
        tid = str(row.get("trace_id") or "").strip()
        if tid and tid in traces:
            out.append(row)
    return out


def load_evaluations_for_tenant(tenant_id: str) -> list[dict[str, Any]] | None:
    """File evaluate receipts for the tenant. None = store absent (unknown)."""
    from decision_api.gnn_loop.receipts import load_receipts, receipt_store_present

    want = (tenant_id or "").strip()
    if not want:
        return None
    if not receipt_store_present(want):
        return None
    return load_receipts(want)


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
                "shadow_divergence": shadow_divergence_rate(sample),
                "window": PACK_METRICS_WINDOW,
                "as_of": as_of,
            }
        )
    return out


def compute_loop_metrics(
    packs: list[dict[str, Any]],
    labels: dict[str, Any],
    *,
    ai_blocked: int = 0,
    ai_passed: int = 0,
    tenant_id: str = "",
    observations: list[dict[str, Any]] | None = None,
    evaluations: list[dict[str, Any]] | None = None,
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

    want = (tenant_id or "").strip()
    unknown_reasons: dict[str, str] = {}
    evaluate_count: int | None
    action_mix: dict[str, int] | None
    if not want:
        evaluate_count = None
        action_mix = None
        shadow_div: float | None = None
        unknown_reasons = {
            "evaluate_count": "empty_tenant",
            "action_mix": "empty_tenant",
            "shadow_divergence": "empty_tenant",
        }
    else:
        if evaluations is None:
            evaluate_count = None
            action_mix = None
            unknown_reasons["evaluate_count"] = "evaluate_store_absent"
            unknown_reasons["action_mix"] = "evaluate_store_absent"
            scoped_evals: list[dict[str, Any]] = []
        else:
            scoped_evals = _tenant_rows(evaluations, want)
            evaluate_count = len(scoped_evals)
            mix: dict[str, int] = {}
            for row in scoped_evals:
                token = _action_token(row)
                if token:
                    mix[token] = mix.get(token, 0) + 1
            action_mix = mix or None
        pairs = [
            _with_diverged(row)
            for row in _global_observation_rows(observations, want, scoped_evals)
            if _is_shadow_pair(row)
        ]
        shadow_div = shadow_divergence_rate(pairs)
        if shadow_div is None:
            unknown_reasons["shadow_divergence"] = "no_shadow_live_pairs"

    reason_code = None
    if unknown_reasons:
        reason_code = (
            unknown_reasons.get("evaluate_count")
            or unknown_reasons.get("shadow_divergence")
            or next(iter(unknown_reasons.values()))
        )

    payload: dict[str, Any] = {
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
        "evaluate_count": evaluate_count,
        "action_mix": action_mix,
        "rule_hit_rate": None,
        "shadow_divergence": shadow_div,
        "pack_metrics": compute_pack_metrics(packs, observations, tenant_id=tenant_id),
    }
    if reason_code:
        payload["reason_code"] = reason_code
        payload["unknown_reasons"] = unknown_reasons
    return payload
