"""Structured errors from Rust ``evaluate`` (FFI → :class:`ManifestIntegrityError`)."""

from __future__ import annotations

import pytest

from tarka.decision import evaluate
from tarka.verifier import ManifestIntegrityError, VerificationFailureReason


def test_wrong_rule_content_id_maps_to_canonicalization() -> None:
    rule_json = '{"kind":"compare_leaf","id":"x","path":"/v","op":"eq","expected":1}'
    wrong_hex = "0" * 64
    with pytest.raises(ManifestIntegrityError) as excinfo:
        evaluate(rule_json, '{"v": 1}', wrong_hex, fast_path=True)
    assert excinfo.value.failure_reason == VerificationFailureReason.CANONICALIZATION_ERROR
