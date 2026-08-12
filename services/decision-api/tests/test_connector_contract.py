"""Connector contract posture — fail-closed LIVE claims."""

from __future__ import annotations

import os

import pytest

from decision_api.connector_contract import (
    load_all_connector_posture,
    posture_for_family,
)


@pytest.fixture(autouse=True)
def _clear_vendor_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("TARKA_VENDOR_"):
            monkeypatch.delenv(key, raising=False)


def test_device_unavailable_without_creds():
    out = posture_for_family("device", registered_vendors=[])
    assert out["live_claim_allowed"] is False
    assert "credentials_missing" in out["blockers"]
    assert out["status"] == "unavailable"


def test_device_partial_when_creds_but_not_registered(monkeypatch):
    monkeypatch.setenv("TARKA_VENDOR_FINGERPRINT_API_KEY", "fp-test-key-xxxx")
    out = posture_for_family("device", registered_vendors=[])
    assert out["live_claim_allowed"] is False
    assert "plugin_not_registered" in out["blockers"]
    assert out["credentials_present"] is True


def test_device_live_when_fp_registered(monkeypatch):
    monkeypatch.setenv("TARKA_VENDOR_FINGERPRINT_API_KEY", "fp-test-key-xxxx")
    out = posture_for_family("device", registered_vendors=["fingerprint"])
    assert out["live_claim_allowed"] is True
    assert out["status"] == "live_ready"
    assert out["blockers"] == []


def test_chargeback_requires_api_key_and_base(monkeypatch):
    monkeypatch.setenv("TARKA_VENDOR_CHARGEBACK_ALERT_BASE_URL", "https://cb.example")
    out = posture_for_family(
        "chargeback_alert", registered_vendors=["chargeback_alert"]
    )
    assert out["live_claim_allowed"] is False
    assert "credentials_missing" in out["blockers"]

    monkeypatch.setenv("TARKA_VENDOR_CHARGEBACK_ALERT_API_KEY", "cb-key-xxxx")
    monkeypatch.delenv("TARKA_VENDOR_CHARGEBACK_ALERT_BASE_URL", raising=False)
    out2 = posture_for_family(
        "chargeback_alert", registered_vendors=["chargeback_alert"]
    )
    assert out2["live_claim_allowed"] is False


def test_chargeback_live_when_ready(monkeypatch):
    monkeypatch.setenv("TARKA_VENDOR_CHARGEBACK_ALERT_API_KEY", "cb-key-xxxx")
    monkeypatch.setenv("TARKA_VENDOR_CHARGEBACK_ALERT_BASE_URL", "https://cb.example")
    out = posture_for_family(
        "chargeback_alert", registered_vendors=["chargeback_alert"]
    )
    assert out["live_claim_allowed"] is True


def test_load_all_includes_marketplace_families():
    out = load_all_connector_posture(registered_vendors=[])
    assert out["schema_id"] == "tarka.connector_ops_posture/v1"
    for fam in (
        "device",
        "identity_kyb",
        "chargeback_alert",
        "sanctions",
        "worker_auth",
        "brand_protection",
    ):
        assert fam in out["families"]
        assert out["families"][fam]["live_claim_allowed"] is False
    assert out["contract"]["fail_closed"] is True
