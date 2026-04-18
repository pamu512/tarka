"""Tenant kill-switch flags (R2.3) and fallback_reason helper (R2.4)."""

from decision_api.main import _compute_fallback_reason
from decision_api.tenant_flags import tenant_flag_enabled


def test_tenant_flag_enabled():
    assert tenant_flag_enabled({"disable_ml": True}, "disable_ml") is True
    assert tenant_flag_enabled({"disable_ml": "true"}, "disable_ml") is True
    assert tenant_flag_enabled({}, "disable_ml") is False


def test_compute_fallback_reason_from_tags():
    r = _compute_fallback_reason(["ml:unavailable", "opa:unavailable"], [])
    assert r
    assert "circuit_ml" in r
    assert "circuit_opa" in r


def test_compute_fallback_reason_rules_only(monkeypatch):
    from decision_api.config import settings

    monkeypatch.setattr(settings, "score_blend_strategy", "rules_only")
    r = _compute_fallback_reason([], [])
    assert r == "rules_only_blend"
