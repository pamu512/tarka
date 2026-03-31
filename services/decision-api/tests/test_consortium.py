from decision_api.consortium import consortium_score_delta, hash_entity_id


def test_hash_entity_id_deterministic():
    h1 = hash_entity_id("secret", "tenant-a", "entity-1")
    h2 = hash_entity_id("secret", "tenant-a", "entity-1")
    assert h1 == h2
    assert len(h1) == 64


def test_hash_entity_id_changes_on_input():
    h1 = hash_entity_id("secret", "tenant-a", "entity-1")
    h2 = hash_entity_id("secret", "tenant-a", "entity-2")
    assert h1 != h2


def test_consortium_score_delta_requires_min_tenants():
    data = {"tenant_count": 1, "report_count": 10, "max_severity": 5}
    assert consortium_score_delta(data, min_tenants=2) == 0.0


def test_consortium_score_delta_caps_value():
    data = {"tenant_count": 10, "report_count": 100, "max_severity": 5}
    assert consortium_score_delta(data, min_tenants=2) == 30.0
