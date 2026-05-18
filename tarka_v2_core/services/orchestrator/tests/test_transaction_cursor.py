"""Unit tests for analytics transaction keyset cursors (no DuckDB required)."""

from orchestrator.analytics.transaction_cursor import decode_transaction_cursor, encode_transaction_cursor


def test_encode_decode_roundtrip() -> None:
    enc = encode_transaction_cursor(ts="2026-05-01T12:00:00+00:00", entity_id="e-1", amount=99.5)
    dec = decode_transaction_cursor(enc)
    assert dec == ("2026-05-01T12:00:00+00:00", "e-1", 99.5)


def test_decode_rejects_garbage() -> None:
    assert decode_transaction_cursor("not-valid") is None
    assert decode_transaction_cursor("") is None
