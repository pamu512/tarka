"""Native device-integrity snapshot + signal tags (no attestation verify)."""

from decision_api.device_integrity import (
    audit_integrity,
    device_integrity_snapshot,
    integrity_presence,
)
from decision_api.main import extract_signal_tags


def test_snapshot_keeps_booleans_including_false():
    snap = device_integrity_snapshot(
        {
            "device_id": "secret-id",
            "platform": "ios",
            "signals": {
                "is_jailbroken": True,
                "has_biometrics": False,
                "is_spoofed_location": False,
            },
            "attestation": {"token": "drop-me", "status": "obtained"},
        }
    )
    assert snap == {
        "platform": "ios",
        "signals": {"is_jailbroken": True, "has_biometrics": False},
        "integrity": {
            "is_rooted": "missing",
            "is_jailbroken": "true",
            "has_biometrics": "present",
        },
    }
    assert "device_id" not in snap
    assert "attestation" not in snap
    assert "is_spoofed_location" not in snap["signals"]


def test_snapshot_omits_absent_booleans():
    snap = device_integrity_snapshot(
        {"platform": "android", "signals": {"is_vpn": True}}
    )
    assert snap == {
        "platform": "android",
        "signals": {},
        "integrity": {
            "is_rooted": "missing",
            "is_jailbroken": "missing",
            "has_biometrics": "missing",
        },
    }
    assert integrity_presence({})["is_rooted"] == "missing"


def test_snapshot_none_and_empty():
    assert device_integrity_snapshot(None) is None
    assert device_integrity_snapshot({}) is None


def test_extract_signal_tags_native_integrity():
    tags = extract_signal_tags(
        {"signals": {"is_rooted": True, "is_jailbroken": True, "has_biometrics": True}}
    )
    assert "sdk:rooted" in tags
    assert "sdk:jailbroken" in tags
    assert "sdk:biometrics" in tags


def test_audit_integrity_always_three_keys():
    assert audit_integrity(None) == {
        "is_rooted": "missing",
        "is_jailbroken": "missing",
        "has_biometrics": "missing",
    }
    assert audit_integrity({"integrity": {"is_rooted": "true"}})["is_rooted"] == "true"
    assert (
        audit_integrity({"integrity": {"is_rooted": "true"}})["is_jailbroken"]
        == "missing"
    )


def test_extract_signal_tags_false_integrity_not_tagged():
    tags = extract_signal_tags(
        {
            "signals": {
                "is_rooted": False,
                "is_jailbroken": False,
                "has_biometrics": False,
            }
        }
    )
    assert "sdk:rooted" not in tags
    assert "sdk:jailbroken" not in tags
    assert "sdk:biometrics" not in tags
