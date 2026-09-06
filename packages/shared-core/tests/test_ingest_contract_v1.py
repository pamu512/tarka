"""Ingest Contract v1 shared helpers."""

import pytest

from tarka_shared.ingest_contract_v1 import (
    IngestContractV1Error,
    SEED_EVENT_TYPES,
    allowed_event_types,
    parse_env_event_types,
    validate_event_type_shape,
    validate_required_envelope_fields,
)


def test_validate_required_envelope_ok():
    out = validate_required_envelope_fields(
        {"tenant_id": " t1 ", "entity_id": " e1 ", "event_type": "payment", "payload": {}}
    )
    assert out["tenant_id"] == "t1"
    assert out["entity_id"] == "e1"
    assert out["event_type"] == "payment"


def test_validate_rejects_bad_event_type():
    with pytest.raises(IngestContractV1Error) as exc:
        validate_required_envelope_fields(
            {"tenant_id": "t1", "entity_id": "e1", "event_type": "wire"}
        )
    assert exc.value.reason_codes == ["ingest_event_type_invalid"]


@pytest.mark.parametrize(
    "body,code",
    [
        ({"entity_id": "e1", "event_type": "login"}, "ingest_tenant_id_empty"),
        ({"tenant_id": "t1", "event_type": "login"}, "ingest_entity_id_empty"),
        ({"tenant_id": "t1", "entity_id": "e1"}, "ingest_event_type_empty"),
    ],
)
def test_validate_rejects_missing(body, code):
    with pytest.raises(IngestContractV1Error) as exc:
        validate_required_envelope_fields(body)
    assert code in exc.value.reason_codes


def test_shape_rejects_bad():
    for bad in ("", "EventCount", "Refund"):
        try:
            validate_event_type_shape(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert validate_event_type_shape(" refund ") == "refund"
    assert validate_event_type_shape("tx_pay") == "tx_pay"


def test_env_and_overlay_allow_refund():
    env = parse_env_event_types("refund, not-a-type, login")
    assert "refund" in env
    assert "not-a-type" not in env
    allowed = allowed_event_types(frozenset({"payout"}), env)
    assert "refund" in allowed and "payout" in allowed and "payment" in allowed


def test_envelope_accepts_allowed_refund():
    out = validate_required_envelope_fields(
        {"tenant_id": "t", "entity_id": "e", "event_type": "refund"},
        allowed=SEED_EVENT_TYPES | frozenset({"refund"}),
    )
    assert out["event_type"] == "refund"
