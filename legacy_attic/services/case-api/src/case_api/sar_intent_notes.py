"""Investigative notes (HTML) + FinCEN submission digest helpers for SAR intents."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

import bleach

from case_api.sar_filing_transport import build_sar_transmission_package
from case_api.sar_transport import SAR_ACKNOWLEDGED, SAR_TRANSMITTED

if TYPE_CHECKING:
    from case_api.models import SARFiling, SarFiling

log = logging.getLogger(__name__)

SAR_UPLOADED_STATUSES = frozenset({SAR_TRANSMITTED, SAR_ACKNOWLEDGED})

_ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "ul",
        "ol",
        "li",
        "a",
        "h1",
        "h2",
        "h3",
        "blockquote",
        "code",
        "pre",
        "span",
    }
)
_ALLOWED_ATTRS = {"a": ["href", "title", "rel", "target"], "span": ["class"]}


def is_sar_uploaded_locked(status: str) -> bool:
    """Uploaded (FinCEN-submitted) intents: notes are immutable; UI shows submission digest."""
    return status in SAR_UPLOADED_STATUSES


def sanitize_investigative_notes_html(raw: str) -> str:
    """Strip XSS and disallowed markup before persistence."""
    if not raw or not str(raw).strip():
        return ""
    return bleach.clean(
        str(raw),
        tags=sorted(_ALLOWED_TAGS),
        attributes=_ALLOWED_ATTRS,
        strip=True,
        protocols=("http", "https", "mailto"),
    )


def fincen_submission_sha256_hex(*, intent: SarFiling, artifact: SARFiling | None) -> str | None:
    """SHA-256 of the exact wire bytes the worker would upload (SR-08 package)."""
    if artifact is None:
        return None
    try:
        _fname, body = build_sar_transmission_package(intent, artifact)
    except Exception:
        log.warning(
            "fincen_submission_sha256_hex: build_sar_transmission_package failed", exc_info=True
        )
        return None
    return hashlib.sha256(body).hexdigest()
