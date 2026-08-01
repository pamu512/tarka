"""Integrity ingress tags + posture helpers (Waves A/B)."""

from decision_api.integrity_policy import (
    apply_evaluate_integrity_tags,
    integrity_ingress_status,
    integrity_policy_matrix,
)


def test_integrity_ingress_status_shape():
    s = integrity_ingress_status(
        request_signature_required=True,
        request_signature_max_skew_seconds=300,
        integrity_soft_tags=True,
        challenge_webhook_configured=False,
        replay_payload_ttl_seconds=120,
    )
    assert s["schema_id"] == "tarka.integrity_ingress/v1"
    assert s["request_signature_required"] is True
    assert s["integrity_soft_tags"] is True
    assert s["challenge_webhook_configured"] is False
    assert s["replay_payload_ttl_seconds"] == 120
    assert "/v1/decisions/evaluate" in s["request_signature_path_prefixes"]


def test_apply_tags_hmac_and_replay_ok():
    tags = apply_evaluate_integrity_tags(
        [],
        hmac_ok=True,
        request_signature_required=True,
        integrity_soft_tags=True,
        tls_pinning_verified=True,
        is_replayed=False,
    )
    assert "ingress:hmac_request_ok" in tags
    assert "ingress:replay_signature_ok" in tags
    assert "ingress:tls_pinning_verified" in tags
    assert "integrity:hmac_not_configured" not in tags


def test_apply_tags_soft_missing_when_unsigned():
    tags = apply_evaluate_integrity_tags(
        [],
        hmac_ok=None,
        request_signature_required=False,
        integrity_soft_tags=True,
        tls_pinning_verified=None,
        is_replayed=False,
    )
    assert "integrity:hmac_not_configured" in tags
    assert "integrity:tls_pinning_unverified" in tags
    assert "ingress:replay_signature_ok" in tags


def test_matrix_still_ships():
    m = integrity_policy_matrix()
    assert m["schema_id"] == "tarka.integrity_policy_matrix/v1"
    assert "server" in m["platforms"]
