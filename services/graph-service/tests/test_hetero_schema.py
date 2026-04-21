"""xFraud #68: typed heterogeneous edges on tenant graph schema."""

import pytest
from graph_service.custom_schema import TenantSchema, invalidate_cache, save_tenant_schema
from graph_service.hetero_schema import validate_typed_edge_or_raise


def test_validate_skips_when_no_typed_edges_configured():
    validate_typed_edge_or_raise("tenant_without_typed_edges_file_xyz", "USED", ["Account"], ["Device"])


def test_validate_accepts_and_rejects_with_saved_schema(tmp_path, monkeypatch):
    monkeypatch.setattr("graph_service.custom_schema._SCHEMAS_DIR", tmp_path)
    invalidate_cache()
    tid = "acme_hetero_demo"
    schema = TenantSchema(
        tenant_id=tid,
        typed_edges=[{"relationship": "USED", "from_entity_types": ["Payment"], "to_entity_types": ["Device"]}],
    )
    save_tenant_schema(schema)
    validate_typed_edge_or_raise(tid, "USED", ["Payment"], ["Device"])
    with pytest.raises(ValueError, match="typed edge USED"):
        validate_typed_edge_or_raise(tid, "USED", ["Person"], ["Device"])


def test_save_tenant_schema_rejects_bad_typed_edge_rel(tmp_path, monkeypatch):
    monkeypatch.setattr("graph_service.custom_schema._SCHEMAS_DIR", tmp_path)
    invalidate_cache()
    bad = TenantSchema(
        tenant_id="badrel",
        typed_edges=[{"relationship": "9INVALID", "from_entity_types": ["Payment"], "to_entity_types": ["Device"]}],
    )
    with pytest.raises(ValueError, match="unsafe typed_edges"):
        save_tenant_schema(bad)
