"""Async hooks to investigation-agent (case brief, label extraction)."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from case_api.models import CaseComment

log = logging.getLogger(__name__)

_INVESTIGATION_AGENT_URL = (os.environ.get("INVESTIGATION_AGENT_URL") or "").strip()
_INTERNAL_SECRET = (os.environ.get("INVESTIGATION_INTERNAL_SECRET") or "").strip()

_CASE_BRIEF_MAX_ATTEMPTS = 4
_CASE_BRIEF_BACKOFF_BASE_S = 0.25

_FALLBACK_COMMENT_BODY = (
    "System: Failed to generate automated case brief due to LLM provider unavailability."
)


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


async def fire_case_brief(
    http: httpx.AsyncClient,
    case_dict: dict[str, Any],
    *,
    session: AsyncSession | None = None,
    case_id: uuid.UUID | None = None,
) -> None:
    if not _INVESTIGATION_AGENT_URL:
        return
    url = f"{_INVESTIGATION_AGENT_URL.rstrip('/')}/v1/internal/case-brief"
    last_exc: Exception | None = None
    for attempt in range(_CASE_BRIEF_MAX_ATTEMPTS):
        try:
            r = await http.post(url, json={"case": case_dict}, headers=_upstream_headers(), timeout=45.0)
            r.raise_for_status()
            return
        except Exception as exc:
            last_exc = exc
            log.warning("case brief hook attempt %s/%s failed: %s", attempt + 1, _CASE_BRIEF_MAX_ATTEMPTS, exc)
            if attempt < _CASE_BRIEF_MAX_ATTEMPTS - 1:
                delay = _CASE_BRIEF_BACKOFF_BASE_S * (2**attempt)
                await asyncio.sleep(delay)
    log.error("case brief hook exhausted retries", exc_info=last_exc)
    if session is not None and case_id is not None:
        try:
            session.add(CaseComment(case_id=case_id, author="system", body=_FALLBACK_COMMENT_BODY))
            await session.commit()
        except Exception as db_exc:
            log.error("case brief fallback comment failed: %s", db_exc)


async def fire_label_extraction(http: httpx.AsyncClient, case_dict: dict[str, Any]) -> None:
    if not _INVESTIGATION_AGENT_URL:
        return
    url = f"{_INVESTIGATION_AGENT_URL.rstrip('/')}/v1/internal/label-extract"
    for attempt in range(_CASE_BRIEF_MAX_ATTEMPTS):
        try:
            r = await http.post(url, json={"case": case_dict}, headers=_upstream_headers(), timeout=60.0)
            r.raise_for_status()
            return
        except Exception as exc:
            log.warning("label extract hook attempt %s/%s failed: %s", attempt + 1, _CASE_BRIEF_MAX_ATTEMPTS, exc)
            if attempt < _CASE_BRIEF_MAX_ATTEMPTS - 1:
                await asyncio.sleep(_CASE_BRIEF_BACKOFF_BASE_S * (2**attempt))
