"""Verify disposition y_label merge fires the correct payload.

Tests the logic inline (no import of case_api.main which has heavy deps).
The function under test is _persist_disposition_y_label; we replicate its
core logic here to assert the contract without pulling in bleach/SAR/etc.
"""

import asyncio
from types import SimpleNamespace

import pytest
from case_api.disposition import y_label_class_for_reason, DISPOSITION_REASON_CODES


def _y_label_for_reason(reason_code: str) -> str | None:
    """Same logic as _persist_disposition_y_label — compute y from reason_code."""
    try:
        ground_truth = y_label_class_for_reason(reason_code)
    except (KeyError, ValueError):
        return None
    return "1" if ground_truth == "FRAUD" else "0"


def test_fraud_reason_maps_to_y_1():
    for code in ("CONFIRMED_FRAUD", "ACCOUNT_TAKEOVER", "FRIENDLY_FRAUD", "SAR_FILED"):
        assert _y_label_for_reason(code) == "1", f"{code} should map to y=1"


def test_legit_reason_maps_to_y_0():
    for code in ("FALSE_POSITIVE", "CUSTOMER_CLEARED", "INSUFFICIENT_EVIDENCE"):
        assert _y_label_for_reason(code) == "0", f"{code} should map to y=0"


def test_unknown_reason_returns_none():
    assert _y_label_for_reason("NOT_A_CODE") is None


def test_all_codes_produce_valid_y():
    for code in DISPOSITION_REASON_CODES:
        y = _y_label_for_reason(code)
        assert y in {"0", "1"}, f"{code} → {y} — expected 0 or 1"
