"""SDK bind: integrity present|missing|true and device_signals pack fire.

Omitted jailbreak / biometrics / root must never become False in the feature
bag or look clean on the evaluate snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

from decision_api.device_feature_merge import merge_device_context_into_features
from decision_api.device_integrity import audit_integrity, integrity_presence
from decision_api.schemas import DeviceContextIn

_PACK_PATH = Path(__file__).resolve().parent.parent / "rules" / "device_signals.json"


def _device_signals_pack() -> dict:
    pack = json.loads(_PACK_PATH.read_text(encoding="utf-8"))
    pack["_source_file"] = "device_signals.json"
    return pack


def _is_true_hits(pack: dict, features: dict) -> list[str]:
    """Same contract as json_rules ``is_true``: only ``actual is True`` fires."""
    hits: list[str] = []
    for rule in pack.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        when = rule.get("when") or []
        if not when:
            continue
        if all(
            isinstance(cond, dict)
            and cond.get("op") == "is_true"
            and features.get(cond.get("field")) is True
            for cond in when
        ):
            hits.append(str(rule.get("id")))
    return hits


def test_integrity_presence_true_present_missing():
    assert integrity_presence({"is_rooted": True, "is_jailbroken": False}) == {
        "is_rooted": "true",
        "is_jailbroken": "present",
        "has_biometrics": "missing",
    }


def test_audit_integrity_fills_missing_keys():
    assert audit_integrity(None)["is_rooted"] == "missing"
    assert audit_integrity({"integrity": {"is_rooted": "true"}}) == {
        "is_rooted": "true",
        "is_jailbroken": "missing",
        "has_biometrics": "missing",
    }


def test_integrity_presence_omitted_is_missing_not_false():
    out = integrity_presence({"is_vpn": True})
    assert out == {
        "is_rooted": "missing",
        "is_jailbroken": "missing",
        "has_biometrics": "missing",
    }
    assert "false" not in out.values()


def test_merge_omitted_integrity_not_invented_false():
    features: dict = {}
    merge_device_context_into_features(
        features,
        DeviceContextIn(
            device_id="dev-1",
            platform="android",
            signals={"is_emulator": True},
        ),
    )
    assert features["is_emulator"] is True
    assert "is_rooted" not in features
    assert "is_jailbroken" not in features
    assert "has_biometrics" not in features


def test_merge_keeps_explicit_false_integrity():
    features: dict = {}
    merge_device_context_into_features(
        features,
        DeviceContextIn(
            device_id="dev-1",
            platform="android",
            signals={"is_rooted": False},
        ),
    )
    assert features["is_rooted"] is False


def test_merge_skips_non_bool_integrity():
    features: dict = {}
    merge_device_context_into_features(
        features,
        DeviceContextIn(
            device_id="dev-1",
            platform="ios",
            signals={"is_rooted": "yes", "is_jailbroken": 1},
        ),
    )
    assert "is_rooted" not in features
    assert "is_jailbroken" not in features


def test_pack_fires_sdk_rooted_when_present_true():
    pack = _device_signals_pack()
    rooted = next(r for r in pack["rules"] if r["id"] == "sdk_rooted")
    assert rooted["when"] == [{"op": "is_true", "field": "is_rooted"}]
    assert "sdk:rooted" in rooted["tags"]
    hits = _is_true_hits(pack, {"is_rooted": True})
    assert "sdk_rooted" in hits


def test_pack_omitted_bot_does_not_fire():
    features: dict = {}
    merge_device_context_into_features(
        features,
        DeviceContextIn(device_id="dev-1", platform="web", signals={}),
    )
    assert "is_bot" not in features
    assert "sdk_bot" not in _is_true_hits(_device_signals_pack(), features)


def test_pack_explicit_false_bot_does_not_fire():
    features: dict = {}
    merge_device_context_into_features(
        features,
        DeviceContextIn(device_id="dev-1", platform="web", signals={"is_bot": False}),
    )
    assert features["is_bot"] is False
    assert "sdk_bot" not in _is_true_hits(_device_signals_pack(), features)


def test_pack_true_bot_fires():
    features: dict = {}
    merge_device_context_into_features(
        features,
        DeviceContextIn(device_id="dev-1", platform="web", signals={"is_bot": True}),
    )
    assert features["is_bot"] is True
    assert "sdk_bot" in _is_true_hits(_device_signals_pack(), features)


def test_merge_skips_non_bool_signal_tag_keys():
    features: dict = {}
    merge_device_context_into_features(
        features,
        DeviceContextIn(
            device_id="dev-1",
            platform="web",
            signals={"is_bot": "yes", "is_emulator": 1, "canvas_fp_hash": "abc"},
        ),
    )
    assert "is_bot" not in features
    assert "is_emulator" not in features
    assert features["canvas_fp_hash"] == "abc"


def test_pack_omitted_rooted_does_not_fire_and_is_not_clean():
    features: dict = {"is_emulator": False}
    merge_device_context_into_features(
        features,
        DeviceContextIn(device_id="dev-1", platform="web", signals={}),
    )
    assert "is_rooted" not in features
    presence = integrity_presence({})
    assert presence["is_rooted"] == "missing"

    hits = _is_true_hits(_device_signals_pack(), features)
    assert "sdk_rooted" not in hits
    assert presence["is_rooted"] != "true"
