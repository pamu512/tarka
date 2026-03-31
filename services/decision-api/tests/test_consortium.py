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


def test_hash_entity_id_cross_tenant_consistent():
    h1 = hash_entity_id("secret", "tenant-a", "entity-1")
    h2 = hash_entity_id("secret", "tenant-b", "entity-1")
    assert h1 == h2


def test_consortium_score_delta_requires_min_tenants():
    data = {"tenant_count": 1, "report_count": 10, "max_severity": 5}
    assert consortium_score_delta(data, min_tenants=2) == 6.0


def test_consortium_score_delta_caps_value():
    data = {"tenant_count": 10, "report_count": 100, "max_severity": 5}
    assert consortium_score_delta(data, min_tenants=2) == 35.0


def test_consortium_score_delta_penalizes_false_positive_rate():
    good = consortium_score_delta(
        {"tenant_count": 3, "weighted_tenant_score": 3.0, "weighted_report_score": 6.0, "max_severity": 3.0, "false_positive_rate": 0.0},
        min_tenants=2,
    )
    bad = consortium_score_delta(
        {"tenant_count": 3, "weighted_tenant_score": 3.0, "weighted_report_score": 6.0, "max_severity": 3.0, "false_positive_rate": 0.8},
        min_tenants=2,
    )
    assert bad < good
