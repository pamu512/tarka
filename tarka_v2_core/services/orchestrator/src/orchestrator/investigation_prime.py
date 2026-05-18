"""Extract candidate transaction / order identifiers from uploaded analyst documents."""

from __future__ import annotations

import re
from io import BytesIO
from typing import Final

# UUID (any version hex shape commonly used as transaction_id / entity_id).
_UUID_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b",
)
# Order-style identifiers (ORD-12345, ORDER_ABC, Order ID: X).
_ORDER_LIKE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:ORD|ORDER)[-_#]?\s*[A-Z0-9][A-Z0-9_-]{3,}\b",
    re.IGNORECASE,
)
# Transaction token prefixes seen in fraud ops tooling.
_TXN_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:TXN|TX|TRX)[-_#]?\s*[A-Z0-9][A-Z0-9_-]{3,}\b",
    re.IGNORECASE,
)
# Customer-style tokens (e.g. cust_99, cust-12) for Knowledge Drop → graph anchor User.user_id.
_CUST_ID_RE: Final[re.Pattern[str]] = re.compile(r"\bcust[_-]\d+\b", re.IGNORECASE)
# Labeled lines common in exports and PDFs.
_ORDER_LABEL_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:order|transaction)\s*id\s*:\s*([A-Z0-9][A-Z0-9_.-]{2,})\b",
)
_PASSPORT_LABEL_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\bpassport\s*(?:no|number|#|id)?\s*:\s*([A-Z0-9][A-Z0-9_.-]{2,})\b",
)
_PASSPORT_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:PP|PPT|PASSPORT)[-_#]?\s*[A-Z0-9][A-Z0-9_-]{3,}\b",
    re.IGNORECASE,
)


def _extract_text_from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise RuntimeError("pypdf is required for PDF priming") from exc
    reader = PdfReader(BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        parts.append(t)
    return "\n".join(parts)


def extract_plaintext_from_upload(*, filename: str, data: bytes) -> str:
    """Return UTF-8-ish plaintext for supported extensions."""
    lower = filename.lower().strip()
    if lower.endswith(".txt"):
        return data.decode("utf-8", errors="replace")
    if lower.endswith(".pdf"):
        return _extract_text_from_pdf(data)
    raise ValueError(f"unsupported file type (expected .pdf or .txt): {filename!r}")


def extract_candidate_ids(text: str) -> list[str]:
    """
    Collect unique Order / transaction-like tokens from free text.

    Order is stable: UUIDs first, then order-like, then TXN-prefixed, deduped preserving order.
    """
    if not text or not str(text).strip():
        return []
    seen: set[str] = set()
    ordered: list[str] = []

    def _push(m: str) -> None:
        s = m.strip()
        if not s or s in seen:
            return
        seen.add(s)
        ordered.append(s)

    for m in _UUID_RE.findall(text):
        _push(m)
    for m in _ORDER_LABEL_RE.findall(text):
        _push(m)
    for m in _PASSPORT_LABEL_RE.findall(text):
        _push(m)
    for m in _ORDER_LIKE_RE.findall(text):
        _push(m)
    for m in _PASSPORT_TOKEN_RE.findall(text):
        _push(m)
    for m in _TXN_PREFIX_RE.findall(text):
        _push(m)
    for m in _CUST_ID_RE.findall(text):
        _push(m)
    return ordered


def build_prime_prompt(ids: list[str]) -> str:
    if not ids:
        return ""
    bracket = ids[0] if len(ids) == 1 else ", ".join(ids)
    return (
        f"I've detected IDs [{bracket}] in the uploaded documents. "
        "Should I cross-reference these with the current case?"
    )


def prime_from_upload(*, filename: str, data: bytes) -> tuple[list[str], str]:
    """Parse upload bytes → ``(detected_ids, prime_prompt)``."""
    text = extract_plaintext_from_upload(filename=filename, data=data)
    ids = extract_candidate_ids(text)
    prompt = build_prime_prompt(ids)
    return ids, prompt
