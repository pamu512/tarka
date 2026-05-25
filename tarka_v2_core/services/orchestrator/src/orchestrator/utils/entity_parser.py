"""
Regex / heuristic extraction of common identifiers from free text (chargebacks, emails, tickets).

Extracts:
  * Order IDs ``ORD-`` + exactly 8 digits (case-sensitive ``ORD`` prefix per product spec).
  * Email-shaped tokens (practical RFC 5322 subset).
  * Carrier-style tracking numbers (UPS ``1Z…``, USPS ``9…`` long numerics, FedEx 12/14/20 digit runs).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# Strict marketplace order token (Prompt 120).
_ORD_EIGHT_RE: Final[re.Pattern[str]] = re.compile(r"\bORD-\d{8}\b")

# Practical email (avoids most obvious HTML / path false positives).
_EMAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}"
    # Do not include ``.`` here: sentence punctuation after ``.com`` must end the match.
    r"(?![A-Za-z0-9_%+-])",
)

# UPS: 1Z + 16 alphanumeric (checksum position varies by service).
_UPS_RE: Final[re.Pattern[str]] = re.compile(r"\b1Z[A-Z0-9]{16}\b", re.IGNORECASE)

# USPS domestic / international-looking long numeric strings (22–30 digits, leading 9).
_USPS_LONG_RE: Final[re.Pattern[str]] = re.compile(r"\b9[0-9]{21,29}\b")

# FedEx / generic express: isolated 12-, 14-, or 20-digit tracking (word boundaries).
# Applied only to substrings not already captured as USPS long numeric.
_FEDEX_LIKE_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:\d{20}|\d{14}|\d{12})\b")


def _push_unique(ordered: list[str], seen: set[str], value: str) -> None:
    v = value.strip()
    if not v or v in seen:
        return
    seen.add(v)
    ordered.append(v)


def _collect_pattern(
    text: str, pattern: re.Pattern[str], ordered: list[str], seen: set[str]
) -> None:
    for m in pattern.finditer(text):
        _push_unique(ordered, seen, m.group(0))


def _fedex_like_without_usps_overlap(
    text: str, usps_hits: set[str], ordered: list[str], seen: set[str]
) -> None:
    for m in _FEDEX_LIKE_RE.finditer(text):
        span = m.group(0)
        if any(span in u or u in span for u in usps_hits):
            continue
        # Do not steal the 8-digit tail from ORD-XXXXXXXX (ORD- is non-digit before digits).
        _push_unique(ordered, seen, span)


@dataclass(frozen=True, slots=True)
class ParsedEntities:
    """Structured hits from ``parse_entities``."""

    order_ids: tuple[str, ...]
    emails: tuple[str, ...]
    tracking_numbers: tuple[str, ...]


def parse_entities(text: str) -> ParsedEntities:
    """
    Scan *text* for order IDs, emails, and tracking-style tokens.

    Order IDs use the strict ``ORD-[0-9]{8}`` shape only (not ``ord-`` / ``ORD12345678``).
    """
    raw = text if isinstance(text, str) else str(text)
    if not raw.strip():
        return ParsedEntities((), (), ())

    order_ids: list[str] = []
    emails: list[str] = []
    tracking: list[str] = []
    seen_order: set[str] = set()
    seen_email: set[str] = set()
    seen_track: set[str] = set()

    _collect_pattern(raw, _ORD_EIGHT_RE, order_ids, seen_order)
    _collect_pattern(raw, _EMAIL_RE, emails, seen_email)

    _collect_pattern(raw, _UPS_RE, tracking, seen_track)
    _collect_pattern(raw, _USPS_LONG_RE, tracking, seen_track)
    usps_set = {t for t in tracking if _USPS_LONG_RE.fullmatch(t)}
    _fedex_like_without_usps_overlap(raw, usps_set, tracking, seen_track)

    return ParsedEntities(
        order_ids=tuple(order_ids),
        emails=tuple(emails),
        tracking_numbers=tuple(tracking),
    )
