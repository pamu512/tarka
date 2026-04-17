from fraud_stack_sdk.request_signing import build_signature_headers, verify_signature


def test_hmac_roundtrip():
    body = b'{"tenant_id":"t"}'
    h = build_signature_headers(body, secret="s", timestamp=1700000000)
    assert "X-Tarka-Timestamp" in h and "X-Tarka-Signature" in h
    ok = verify_signature(
        body,
        {k.lower(): v for k, v in h.items()},
        secret="s",
        max_skew_seconds=999999999,
    )
    assert ok
