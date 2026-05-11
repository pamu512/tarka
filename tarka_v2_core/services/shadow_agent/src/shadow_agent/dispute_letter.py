"""Automated chargeback **representment** letter (Markdown) for Shadow / ops workflows (Prompt 126)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Placeholders are token-shaped to avoid collisions with user Markdown.
_REPRESENTMENT_MARKDOWN = """# Representment / dispute response draft

**Generated (UTC):** __GENERATED_AT__

## Cryptographic event anchor

This bundle references a single canonical fraud / risk event. The **SHA-256** digest below
binds the representment to that immutable record:

| Field | Value |
|------|-------|
| **Cryptographic event hash (SHA-256, hex)** | `__CRYPTOGRAPHIC_EVENT_HASH__` |

## Evidence summary

| Evidence class | Value |
|----------------|-------|
| **Ingress / session IP** | `__IP_ADDRESS__` |
| **Device hash** | `__DEVICE_HASH__` |
| **Signature / authorization evidence** | __SIGNATURE_EVIDENCE__ |

## Representment narrative (template)

The merchant submits that the disputed transaction was authenticated using the device and
network context above, and that the cardholder authorization artifacts (signature / SCA /
digital acceptance) are consistent with prior **non-fraudulent** behavior on file.

> **Note:** This draft is machine-assembled for analyst review. Counsel must validate facts,
> jurisdiction, and scheme rules before filing.

---
*Shadow AI — ``generate_dispute_letter`` tool*
"""


def compute_cryptographic_event_hash(canonical_event: dict[str, Any]) -> str:
    """
    Deterministic **SHA-256** over a canonical JSON object (sorted keys, compact separators).

    Callers should pass the same ``canonical_event`` they used to derive the digest shown to
    the card network / audit trail so the letter hash matches the recorded **cryptographic event
    hash**.
    """
    blob = json.dumps(canonical_event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class RepresentmentLetterIn(BaseModel):
    """Inputs for :func:`generate_dispute_letter`."""

    model_config = ConfigDict(extra="forbid")

    ip_address: str = Field(..., min_length=1, max_length=512)
    device_hash: str = Field(..., min_length=1, max_length=512)
    signature_evidence: str = Field(
        ...,
        min_length=1,
        max_length=8192,
        description="Cardholder signature image ref, e-sign audit id, 3DS outcome, etc.",
    )
    cryptographic_event_hash: str | None = Field(
        default=None,
        max_length=128,
        description="Lowercase hex SHA-256 of the canonical event (64 nibbles).",
    )
    canonical_event: dict[str, Any] | None = Field(
        default=None,
        description="If ``cryptographic_event_hash`` is omitted, the digest is derived from this object.",
    )

    @model_validator(mode="after")
    def _require_hash_or_canonical(self) -> Self:
        if self.cryptographic_event_hash is None and not self.canonical_event:
            raise ValueError("Provide cryptographic_event_hash and/or canonical_event")
        return self


class RepresentmentLetterOut(BaseModel):
    """Markdown letter plus the effective cryptographic hash echoed for verification."""

    model_config = ConfigDict(extra="forbid")

    letter_markdown: str
    cryptographic_event_hash: str


def _escape_md_cell(value: str) -> str:
    """Avoid breaking Markdown tables when values contain pipes or newlines."""
    s = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    s = s.replace("|", "\\|")
    if "\n" in s:
        return "<br>".join(s.split("\n"))
    return s


def generate_dispute_letter(evidence: RepresentmentLetterIn) -> RepresentmentLetterOut:
    """
    Fill the representment Markdown template with **IP**, **device hash**, and **signature**
    evidence, and embed the **cryptographic event hash** (caller-supplied or derived from
    ``canonical_event``).
    """
    h_in = (evidence.cryptographic_event_hash or "").strip().lower()
    if evidence.canonical_event is not None:
        derived = compute_cryptographic_event_hash(evidence.canonical_event)
        if h_in and h_in != derived:
            raise ValueError("cryptographic_event_hash does not match canonical_event payload")
        event_hash = derived
    else:
        if not h_in:
            raise ValueError("cryptographic_event_hash is required when canonical_event is omitted")
        event_hash = h_in

    if len(event_hash) != 64 or any(c not in "0123456789abcdef" for c in event_hash):
        raise ValueError("cryptographic_event_hash must be 64 lowercase hex characters")

    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    body = (
        _REPRESENTMENT_MARKDOWN.replace("__GENERATED_AT__", generated)
        .replace("__CRYPTOGRAPHIC_EVENT_HASH__", event_hash)
        .replace("__IP_ADDRESS__", _escape_md_cell(evidence.ip_address))
        .replace("__DEVICE_HASH__", _escape_md_cell(evidence.device_hash))
        .replace("__SIGNATURE_EVIDENCE__", _escape_md_cell(evidence.signature_evidence))
    )
    return RepresentmentLetterOut(letter_markdown=body, cryptographic_event_hash=event_hash)
