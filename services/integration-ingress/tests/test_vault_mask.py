"""Vault masking hints for integration credentials (UI contract)."""

from integration_ingress.vault import _mask


def test_mask_short_value() -> None:
    assert _mask("") == ""
    assert _mask("ab") == "••••"


def test_mask_long_value_last_four() -> None:
    assert _mask("sk_live_abcdefghijklmnop") == "••••mnop"
