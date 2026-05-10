"""Strip prompt-injection patterns from transaction text before LLM system prompts."""

from __future__ import annotations

import re
from typing import Any

from ingestor.schemas import TransactionSchema

# Common delimiter / role-marker leaks used to hijack chat templates.
_MARKERS = (
    re.compile(r"<\|[^|\n]{1,128}\|>", re.DOTALL),
    re.compile(r"\[/?INST\]", re.IGNORECASE),
    re.compile(r"\[/?SYSTEM\]", re.IGNORECASE),
    re.compile(r"\[/?HUMAN\]", re.IGNORECASE),
    re.compile(r"###\s*(System|Instruction|Human|Assistant)\s*:?", re.IGNORECASE),
)

# Natural-language override attempts (bounded phrases; case-insensitive).
_PHRASES = (
    # Broad jailbreak line (must run before narrower ``ignore all rules`` fragments).
    re.compile(
        r"\bignore\s+all\s+rules\s+and\s+return\b[^\n]{0,240}",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bignore\s+(all\s+)?(prior|previous)\s+instructions?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdisregard\s+(all\s+)?(prior|previous)\s+instructions?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bignore\s+all\s+rules\b(?:[^\n.!?]{0,160})?",
        re.IGNORECASE,
    ),
)


def _sanitize_string(value: str) -> str:
    """Remove known injection markers and phrases; collapse leftover whitespace."""
    out = value
    for pat in _MARKERS:
        out = pat.sub("", out)
    for pat in _PHRASES:
        out = pat.sub("", out)
    out = re.sub(r"[ \t\r\f\v]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _sanitize_jsonish(obj: Any) -> Any:
    if isinstance(obj, str):
        return _sanitize_string(obj)
    if isinstance(obj, dict):
        return {k: _sanitize_jsonish(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_jsonish(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_jsonish(x) for x in obj)
    return obj


def sanitize_transaction_for_prompt(tx: TransactionSchema) -> TransactionSchema:
    """
    Return a shallow copy of ``tx`` with ``metadata`` text recursively sanitized.

    Numeric and temporal fields are unchanged (they are not interpolated as free text).
    """
    return tx.model_copy(update={"metadata": _sanitize_jsonish(tx.metadata)})
