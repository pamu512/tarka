"""Additional fuzz: invalid binary / protobuf-style payloads and JSON boundaries.

OpenAPI for Decision API is JSON-first; clients sending opaque bytes must never crash the server.
These tests complement Schemathesis with explicit Hypothesis strategies (including invalid protobuf
wire encodings: truncated length-delimited frames, unterminated varints, junk tags).
"""

from __future__ import annotations

import json

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from tests.contract.schemathesis_config import binary_fuzz_max_examples

pytestmark = pytest.mark.contract

_BOUNDARY_EXAMPLES = binary_fuzz_max_examples()

_SHARED_CLIENT_CHECKS = settings(
    max_examples=_BOUNDARY_EXAMPLES,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)

_DEEP_JSON_CHECKS = settings(
    max_examples=min(_BOUNDARY_EXAMPLES, 60),
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)

# Hand-crafted protobuf wire edge cases (length-delimited / varint / invalid wire types).
_PROTO_MISHAP_SEEDS = [
    bytes([0x08, 0x80, 0x80, 0x80, 0x80, 0x80, 0x01]),  # varint field 1, non-terminal high bits
    bytes([0x0A, 0xFF, 0xFF, 0xFF, 0x0F]),  # LEN field 1, absurd declared length, no payload
    bytes([0x12, 0x05, 0x41, 0x42, 0x43]),  # string len 5, truncated payload
    bytes([0x1A, 0x00]),  # empty length-delimited
    bytes([0xFF, 0xFF, 0xFF, 0xFF, 0x0F]),  # max-tag style varint noise
    b"\x08",  # single-byte field without value
    bytes([0x72, 0x02, 0x01]),  # wire type 2 with length 2, one byte of payload
]


@st.composite
def _protobuf_wire_mishaps(draw) -> bytes:
    head = draw(st.sampled_from(_PROTO_MISHAP_SEEDS))
    tail = draw(st.binary(max_size=8_192))
    return head + tail


@_SHARED_CLIENT_CHECKS
@given(payload=st.binary(min_size=0, max_size=48_000))
def test_evaluate_binary_body_never_500(httpx_client, payload):
    """Random octets as ``application/x-protobuf`` must not uncaught-exception the ASGI stack."""
    r = httpx_client.post(
        "/v1/decisions/evaluate",
        content=payload,
        headers={
            "Content-Type": "application/x-protobuf",
            "Accept": "application/json",
        },
    )
    assert r.status_code < 500, r.text[:500]


@_SHARED_CLIENT_CHECKS
@given(payload=st.binary(min_size=0, max_size=48_000))
def test_evaluate_octet_stream_never_500(httpx_client, payload):
    r = httpx_client.post(
        "/v1/decisions/evaluate",
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code < 500, r.text[:500]


@_SHARED_CLIENT_CHECKS
@given(text=st.text(min_size=0, max_size=16_000))
def test_evaluate_invalid_json_string_body_never_500(httpx_client, text):
    # Python's ``json.loads`` accepts ``Infinity`` / ``NaN`` as top-level scalars; those are valid
    # JSON under Python's decoder but not ``EvaluateRequest`` documents — skip to keep this test
    # focused on **syntactically invalid** JSON and malformed UTF-8-ish strings.
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        if not isinstance(parsed, dict):
            assume(False)

    r = httpx_client.post(
        "/v1/decisions/evaluate",
        content=text.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code < 500, r.text[:500]


@_SHARED_CLIENT_CHECKS
@given(payload=_protobuf_wire_mishaps())
def test_evaluate_invalid_protobuf_wire_never_500(httpx_client, payload):
    """Malformed length-delimited / varint frames as ``application/x-protobuf`` must not 5xx."""
    r = httpx_client.post(
        "/v1/decisions/evaluate",
        content=payload,
        headers={
            "Content-Type": "application/x-protobuf",
            "Accept": "application/json",
        },
    )
    assert r.status_code < 500, r.text[:500]


@_DEEP_JSON_CHECKS
@given(
    key=st.text(alphabet=st.characters(min_codepoint=1, blacklist_categories=("Cs",)), max_size=64),
    depth=st.integers(min_value=0, max_value=6),
)
def test_evaluate_deep_json_structure_never_500(httpx_client, key, depth):
    """Nested JSON shapes — catches stack blowups / naive recursion in validators."""

    def nest(level: int) -> dict:
        if level <= 0:
            return {"event_type": "login", "amount": 1}
        return {key or "k": nest(level - 1)}

    body = json.dumps(nest(depth)).encode()
    r = httpx_client.post(
        "/v1/decisions/evaluate",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code < 500, r.text[:500]
