"""Fail-soft HTTP client for the decision context graph (graph-service).

Never raises to callers. Controlled by DECISION_GRAPH_ENABLED + GRAPH_SERVICE_URL
(or DECISION_GRAPH_URL). Timeout defaults to 2s.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("tarka.decision_graph")


def _enabled() -> bool:
    raw = (os.environ.get("DECISION_GRAPH_ENABLED") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _base_url() -> str:
    for key in ("DECISION_GRAPH_URL", "GRAPH_SERVICE_URL"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v.rstrip("/")
    return ""


def _timeout() -> float:
    try:
        return max(0.2, min(float(os.environ.get("DECISION_GRAPH_TIMEOUT_SECONDS") or "2"), 10.0))
    except ValueError:
        return 2.0


def _headers() -> dict[str, str]:
    key = (os.environ.get("GRAPH_SERVICE_API_KEY") or os.environ.get("API_KEY") or "").strip()
    h = {"Content-Type": "application/json"}
    if key:
        h["X-API-Key"] = key
    return h


def record_decision_failsoft(payload: dict[str, Any]) -> str | None:
    """POST /v1/decisions. Returns external_id or None on any failure / disabled."""
    if not _enabled():
        return None
    base = _base_url()
    if not base:
        log.debug("decision_graph_skip reason=no_url")
        return None
    try:
        import httpx
    except ImportError:
        log.warning("decision_graph_skip reason=no_httpx")
        return None
    try:
        with httpx.Client(timeout=_timeout()) as client:
            r = client.post(f"{base}/v1/decisions", json=payload, headers=_headers())
            if r.status_code >= 400:
                log.warning(
                    "decision_graph_write_fail status=%s body=%s",
                    r.status_code,
                    (r.text or "")[:200],
                )
                return None
            data = r.json()
            return str(data.get("external_id") or "") or None
    except Exception:
        log.warning("decision_graph_write_fail", exc_info=True)
        return None


def get_chain_failsoft(tenant_id: str, external_id: str, max_depth: int = 5) -> dict[str, Any] | None:
    if not _enabled():
        return None
    base = _base_url()
    if not base:
        return None
    try:
        import httpx
    except ImportError:
        return None
    try:
        with httpx.Client(timeout=_timeout()) as client:
            r = client.get(
                f"{base}/v1/decisions/{external_id}/chain",
                params={"tenant_id": tenant_id, "max_depth": max_depth},
                headers=_headers(),
            )
            if r.status_code >= 400:
                return None
            return r.json()
    except Exception:
        log.warning("decision_graph_chain_fail", exc_info=True)
        return None
