"""Ingest Contract v1 shared helpers."""

import pytest

from tarka_shared.ingest_contract_v1 import (
    IngestContractV1Error,
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
