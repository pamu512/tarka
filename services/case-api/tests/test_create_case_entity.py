import pytest
from case_api.schemas import CreateCaseRequest
from pydantic import ValidationError


def test_blank_entity_id_rejected():
    with pytest.raises(ValidationError, match="entity_id"):
        CreateCaseRequest(tenant_id="t", title="x", entity_id="  ", trace_id="tr")


def test_entity_id_stripped():
    r = CreateCaseRequest(tenant_id="t", title="x", entity_id="  e1  ", trace_id="tr")
    assert r.entity_id == "e1"
