from __future__ import annotations

import json

from feature_flags import feature_enabled


def test_feature_enabled_defaults(monkeypatch):
    monkeypatch.delenv("FEATURE_FLAGS_JSON", raising=False)
    assert feature_enabled("unknown_feature", tenant_id="t1", default=False) is False
    assert feature_enabled("unknown_feature", tenant_id="t1", default=True) is True


def test_feature_enabled_tenant_override(monkeypatch):
    monkeypatch.setenv(
        "FEATURE_FLAGS_JSON",
        json.dumps(
            {
                "decision_api_external_signals": {
                    "enabled": True,
                    "rollout_pct": 0,
                    "tenants": ["tenant-a"],
                }
            }
        ),
    )
    assert feature_enabled("decision_api_external_signals", tenant_id="tenant-a", default=False) is True
    assert feature_enabled("decision_api_external_signals", tenant_id="tenant-b", default=False) is False


def test_feature_enabled_rollout_deterministic(monkeypatch):
    monkeypatch.setenv(
        "FEATURE_FLAGS_JSON",
        json.dumps(
            {
                "decision_api_shadow_eval_async": {
                    "enabled": True,
                    "rollout_pct": 50,
                }
            }
        ),
    )
    a = feature_enabled("decision_api_shadow_eval_async", tenant_id="tenant-z", default=False)
    b = feature_enabled("decision_api_shadow_eval_async", tenant_id="tenant-z", default=False)
    assert a is b

