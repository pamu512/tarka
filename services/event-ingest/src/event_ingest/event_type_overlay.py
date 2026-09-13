"""Tenant event-type overlay client for the ingest allow-list.

When an ``event_type`` misses seed ∪ ``TARKA_EVENT_TYPES``, event-ingest consults
decision-api ``GET /v1/event-types?tenant_id=...`` (the tenant overlay persisted on
Postgres, migration ``20260906_011``) before rejecting. This closes the split-brain
where the management plane accepted a tenant-added type but the ingest plane 422'd it.

Semantics:
- Hot path: a seed/env hit never touches decision-api.
- Positive cache: per-tenant name set cached for ``event_type_overlay_ttl_seconds``
  (default 30s). Newly added types propagate within the TTL.
- Negative cache: an empty overlay result is held for ``_NEG_CACHE_S`` (2s) so a
  burst of unknown types cannot hammer decision-api; a just-added type still
  propagates within 2s.
- Fail-closed: on any fetch error the overlay is treated as empty and the failure is
  backed off briefly (``_FAIL_BACKOFF_S``) so recovery is quick; seed ∪ env still
  apply, i.e. behavior degrades to the pre-overlay contract — never fail-open.
"""

from __future__ import annotations

import logging
import time

import httpx

from .config import settings

log = logging.getLogger(__name__)

_FAIL_BACKOFF_S = 5.0
_NEG_CACHE_S = 2.0
_MAX_CACHE_TENANTS = 4096

_names_cache: dict[str, tuple[float, frozenset[str]]] = {}
_fail_until: dict[str, float] = {}
_fail_logged = False


def _bump_metric(name: str) -> None:
    """Best-effort counter; observability may not be importable in all contexts."""
    try:
        from observability import get_metrics

        get_metrics().inc(name)
    except Exception:
        pass


def _reset_for_tests() -> None:
    _names_cache.clear()
    _fail_until.clear()
    global _fail_logged
    _fail_logged = False


async def tenant_overlay_names(http: httpx.AsyncClient, tenant_id: str) -> frozenset[str]:
    """Allowed overlay names for *tenant_id* (empty frozenset on any failure)."""
    global _fail_logged
    now = time.monotonic()
    cached = _names_cache.get(tenant_id)
    if cached is not None and cached[0] > now:
        return cached[1]
    if _fail_until.get(tenant_id, 0.0) > now:
        return frozenset()

    # Late import: main.py imports this module; avoid the cycle.
    from .main import _decision_api_headers

    url = f"{settings.decision_api_url.rstrip('/')}/v1/event-types"
    try:
        r = await http.get(
            url,
            params={"tenant_id": tenant_id},
            headers=_decision_api_headers(),
            timeout=5.0,
        )
        r.raise_for_status()
        body = r.json()
        names = frozenset(
            str(n) for n in (body.get("names") or []) if isinstance(n, str)
        )
    except Exception as exc:
        _fail_until[tenant_id] = now + _FAIL_BACKOFF_S
        _bump_metric("ingest_event_type_overlay_fetch_error_total")
        if not _fail_logged:
            log.warning(
                "event-type overlay fetch failed (fail-closed to seed∪env during "
                "backoff): %s",
                exc,
            )
            _fail_logged = True
        return frozenset()

    if len(_names_cache) > _MAX_CACHE_TENANTS:
        _names_cache.clear()
    if names:
        ttl = max(1.0, float(settings.event_type_overlay_ttl_seconds))
    else:
        ttl = _NEG_CACHE_S
    _names_cache[tenant_id] = (now + ttl, names)
    return names
