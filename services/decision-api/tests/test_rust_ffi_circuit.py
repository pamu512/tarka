"""Circuit breaker for Rust FFI (see ``rust_ffi_circuit`` / ``rust_rule_engine_ffi``)."""

from __future__ import annotations

import pytest

from decision_api.rust_ffi_circuit import (
    circuit_is_open,
    failures_in_window,
    record_rust_ffi_failure,
    record_rust_ffi_success,
)


def test_sliding_window_trips_after_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "decision_api.rust_ffi_circuit.settings.rust_ffi_circuit_failure_threshold", 3
    )
    monkeypatch.setattr(
        "decision_api.rust_ffi_circuit.settings.rust_ffi_circuit_window_seconds", 60.0
    )
    record_rust_ffi_success()
    assert failures_in_window() == 0
    record_rust_ffi_failure()
    record_rust_ffi_failure()
    assert circuit_is_open() is False
    record_rust_ffi_failure()
    assert failures_in_window() == 3
    assert circuit_is_open() is True


def test_success_clears_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "decision_api.rust_ffi_circuit.settings.rust_ffi_circuit_failure_threshold", 2
    )
    record_rust_ffi_failure()
    record_rust_ffi_failure()
    assert circuit_is_open() is True
    record_rust_ffi_success()
    assert failures_in_window() == 0
    assert circuit_is_open() is False
