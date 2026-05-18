"""Mobile attestation normalization and signal tags."""

from decision_api.attestation_taxonomy import (
    attestation_signal_tags,
    normalize_attestation_object,
)
from decision_api.main import extract_signal_tags
from decision_api.schemas import DeviceContextIn, EvaluateRequest, EventType


def test_normalize_play_integrity_alias_and_obtained():
    raw = {"nonce": "n", "token": "x" * 60, "provider": "google_play_integrity"}
    out = normalize_attestation_object(raw, platform="android")
    assert out["provider"] == "play_integrity"
    assert out["status"] == "obtained"
    assert out["confidence_tier"] == "medium"
    assert out["attestation_schema_version"] == 1


def test_normalize_obtained_without_token_becomes_failed():
    raw = {"nonce": "n", "token": "", "provider": "play_integrity"}
    out = normalize_attestation_object(raw, platform="android")
    assert out["status"] == "failed"
    assert out["failure_reason"] == "token_unavailable"


def test_device_context_in_validator_normalizes():
    body = EvaluateRequest(
        tenant_id="t1",
        event_type=EventType.login,
        entity_id="e1",
        payload={},
        device_context=DeviceContextIn(
            device_id="d1",
            platform="android",
            signals={},
            attestation={"nonce": "n", "token": "t" * 50, "provider": "play_integrity"},
        ),
    )
    att = body.device_context.attestation
    assert att["status"] == "obtained"


def test_extract_signal_tags_attestation_obtained():
    dc = {
        "device_id": "d",
        "platform": "android",
        "signals": {},
        "attestation": {
            "nonce": "n",
            "token": "t" * 50,
            "provider": "play_integrity",
            "status": "obtained",
            "confidence_tier": "medium",
        },
    }
    tags = extract_signal_tags(dc)
    assert "sdk:attestation_obtained" in tags
    assert "sdk:attestation_play_integrity" in tags


def test_extract_signal_tags_attestation_failed():
    dc = {
        "device_id": "d",
        "platform": "ios",
        "signals": {},
        "attestation": {
            "nonce": "",
            "token": "",
            "provider": "app_attest",
            "status": "failed",
            "failure_reason": "client_error",
            "confidence_tier": "none",
        },
    }
    tags = extract_signal_tags(dc)
    assert "sdk:attestation_failed" in tags
    assert "sdk:attestation_obtained" not in tags


def test_attestation_signal_tags_ios_obtained():
    dc = {
        "platform": "ios",
        "attestation": {
            "provider": "app_attest",
            "status": "obtained",
            "token": "x" * 40,
        },
    }
    tags = attestation_signal_tags(dc)
    assert "sdk:attestation_app_attest" in tags
