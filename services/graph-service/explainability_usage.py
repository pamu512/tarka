from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any

from observability import get_metrics

_lock = Lock()
_events: dict[str, int] = defaultdict(int)


def record_explainability_event(
    surface: str,
    tenant_id: str | None = None,
    *,
    detail: str | None = None,
) -> None:
    key = f"{surface}|{(tenant_id or '').strip() or 'global'}"
    with _lock:
        _events[key] += 1
    try:
        metrics = get_metrics()
        metrics.inc(f"tarka_explainability_{surface}_total")
    except Exception:
        pass


def usage_snapshot() -> dict[str, Any]:
    with _lock:
        by_surface: dict[str, int] = defaultdict(int)
        by_tenant: dict[str, int] = defaultdict(int)
        for key, count in _events.items():
            surface, tenant = key.split("|", 1)
            by_surface[surface] += count
            by_tenant[tenant] += count
        return {
            "schema_id": "tarka.explainability_usage/v1",
            "events_by_surface": dict(sorted(by_surface.items())),
            "events_by_tenant": dict(sorted(by_tenant.items())),
            "total_events": sum(_events.values()),
        }
