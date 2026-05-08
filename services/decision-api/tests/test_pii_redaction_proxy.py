"""PII redaction proxy for auditor-facing audit payloads."""

from decision_api.pii_redaction_proxy import (
    evidence_manifest_json_redact_input_map,
    flatten_payload_to_entry_strings,
    is_superuser,
    mask_email_like,
    redact_flat_payload_entries,
    redact_scalar_string,
)


def test_mask_email_like_preserves_domain_tarka_style() -> None:
    assert mask_email_like("alice@tarka.com") == "a***@tarka.com"


def test_ipv4_preserves_edges() -> None:
    assert "*" in redact_scalar_string("Connection from 203.0.113.10")


def test_flatten_and_redact_entries() -> None:
    payload = {
        "user_email": "sam@example.org",
        "nested": {"client_ip": "198.51.100.7"},
    }
    flat = flatten_payload_to_entry_strings(payload)
    assert "user_email" in flat
    assert "nested.client_ip" in flat
    red = redact_flat_payload_entries(flat)
    assert "@example.org" in red["user_email"]["string_value"]
    assert red["user_email"]["string_value"].startswith("s***")


def test_evidence_manifest_json_redact_input_map() -> None:
    m = {
        "input_map": {
            "entries": {
                "email": {"string_value": "boss@corp.invalid"},
                "score": {"double_value": 1.5},
            }
        }
    }
    out = evidence_manifest_json_redact_input_map(m)
    assert out["input_map"]["entries"]["email"]["string_value"] == "b***@corp.invalid"
    assert out["input_map"]["entries"]["score"]["double_value"] == 1.5


def test_is_superuser_auth_user() -> None:
    class U:
        def __init__(self, ok: bool):
            self._ok = ok

        def has_role(self, r: str) -> bool:
            return self._ok and r == "admin"

    assert is_superuser(U(True)) is True
    assert is_superuser(U(False)) is False
    assert is_superuser(None) is False
