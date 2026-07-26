"""Emit per-reason metrics for evaluate degrade_tags (Phase 1 SLO hooks)."""

from __future__ import annotations

from typing import Any, Callable

# Map degrade tag prefixes / exact tags → metric suffix (snake).
_TAG_METRIC_KEYS: tuple[tuple[str, str], ...] = (
    (
        "circuit_open",
        "circuit_open",
    ),  # unused exact; circuits use tarka_circuit_* already
    ("load_shedding:active", "load_shed"),
    ("feature:missing_", "missing_feature"),
    ("feature:catalog_fail_closed", "catalog_fail_closed"),
    ("graph:stale_skipped", "graph_stale_skipped"),
    ("graph:stale_fail_closed", "graph_stale_fail_closed"),
    ("graph:unavailable", "graph_unavailable"),
    ("enrichment:unavailable", "enrichment_unavailable"),
    ("ml:unavailable", "ml_unavailable"),
    ("lists:unavailable", "lists_unavailable"),
    ("opa:unavailable", "opa_unavailable"),
)


def record_degraded_decision_metrics(
    degrade_tags: list[str] | None,
    *,
    metrics_inc: Callable[..., Any] | None,
    trace_id: Any | None = None,
) -> list[str]:
    """Increment ``tarka_degraded_decision_total`` and per-reason counters.

    Returns the list of reason keys that were emitted (for tests).
    """
    if not degrade_tags or metrics_inc is None:
        return []
    emitted: list[str] = []
    seen: set[str] = set()
    for tag in degrade_tags:
        reason = _reason_for_tag(tag)
        if reason is None or reason in seen:
            continue
        seen.add(reason)
        emitted.append(reason)
        try:
            metrics_inc("tarka_degraded_decision_total", trace_id=trace_id)
            metrics_inc(f"tarka_degraded_decision_{reason}_total", trace_id=trace_id)
        except TypeError:
            # Some callers pass a 1-arg metrics_inc
            try:
                metrics_inc("tarka_degraded_decision_total")
                metrics_inc(f"tarka_degraded_decision_{reason}_total")
            except Exception:
                pass
        except Exception:
            pass
    return emitted


def _reason_for_tag(tag: str) -> str | None:
    t = (tag or "").strip()
    if not t:
        return None
    for prefix, reason in _TAG_METRIC_KEYS:
        if t == prefix or t.startswith(prefix):
            return reason
    if t.startswith("feature:missing_"):
        return "missing_feature"
    return None
