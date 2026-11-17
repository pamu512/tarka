"""Fixed question pack ``advise_sufficiency_v1``. Prompts are code, not model prose."""

from __future__ import annotations

from typing import Any

PACK_ID = "advise_sufficiency_v1"

HAS_ENOUGH_SIGNAL = "has_enough_signal"
REVIEW_PRIORITY = "review_priority"
PATTERN_HINT = "pattern_hint"

SIGNAL_PROMPT = (
    "Does this evidence pack contain enough signal for a useful residual fraud review note?"
)
PRIORITY_PROMPT = "Which residual review priority fits this pack?"
PATTERN_PROMPT = "Closest pattern family (or none)."

REVIEW_PRIORITY_OPTIONS = ("skip_noise", "routine", "urgent")
PATTERN_HINT_OPTIONS = ("none", "velocity", "identity", "network", "claims_pod", "other")

QUESTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": HAS_ENOUGH_SIGNAL,
        "type": "noul",
        "prompt": SIGNAL_PROMPT,
    },
    {
        "id": REVIEW_PRIORITY,
        "type": "choice",
        "prompt": PRIORITY_PROMPT,
        "options": list(REVIEW_PRIORITY_OPTIONS),
    },
    {
        "id": PATTERN_HINT,
        "type": "choice",
        "prompt": PATTERN_PROMPT,
        "options": list(PATTERN_HINT_OPTIONS),
    },
)


def build_systemone_request(evidence: dict[str, Any]) -> dict[str, Any]:
    """One System One call. No free-text fields in the signature."""
    return {
        "pack_id": PACK_ID,
        "evidence": evidence,
        "questions": [dict(q) for q in QUESTIONS],
    }
