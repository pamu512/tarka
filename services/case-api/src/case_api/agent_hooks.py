"""Async hooks to investigation-agent (case brief, label extraction)."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

_INVESTIGATION_AGENT_URL = (os.environ.get("INVESTIGATION_AGENT_URL") or "").strip()
_INTERNAL_SECRET = (os.environ.get("INVESTIGATION_INTERNAL_SECRET") or "").strip()


def _upstream_headers() -> dict[str, str]:
    raw = (os.environ.get("API_KEYS") or "").strip()
    out: dict[str, str] = {}
    if raw:
        key = raw.split(",")[0].strip()
        if key:
            out["x-api-key"] = key
    if _INTERNAL_SECRET:
        out["x-internal-secret"] = _INTERNAL_SECRET
    return out


async def fire_case_brief(http: httpx.AsyncClient, case_dict: dict[str, Any]) -> None:
    if not _INVESTIGATION_AGENT_URL:
        return
    url = f"{_INVESTIGATION_AGENT_URL.rstrip('/')}/v1/internal/case-brief"
    try:
        await http.post(url, json={"case": case_dict}, headers=_upstream_headers(), timeout=45.0)
    except Exception as exc:
        log.debug("case brief hook skipped: %s", exc)


async def fire_label_extraction(http: httpx.AsyncClient, case_dict: dict[str, Any]) -> None:
    if not _INVESTIGATION_AGENT_URL:
        return
    url = f"{_INVESTIGATION_AGENT_URL.rstrip('/')}/v1/internal/label-extract"
    try:
        await http.post(url, json={"case": case_dict}, headers=_upstream_headers(), timeout=60.0)
    except Exception as exc:
        log.debug("label extract hook skipped: %s", exc)
