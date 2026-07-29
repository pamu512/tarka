"""Policy-set identity (Wave C): JSON packs + typology + challenge."""

from decision_api.policy_set import (
    POLICY_SET_SCHEMA,
    bump_policy_set_generation,
    build_policy_set_manifest,
    current_policy_set_id,
    get_policy_set_manifest,
)


def test_manifest_schema_and_stable_id() -> None:
    m1 = build_policy_set_manifest()
    assert m1["schema"] == POLICY_SET_SCHEMA
    assert isinstance(m1["policy_set_id"], str) and len(m1["policy_set_id"]) == 64
    assert "json_packs" in m1["components"]
    assert "typology" in m1["components"]
    assert "challenge_policies" in m1["components"]
    m2 = build_policy_set_manifest()
    assert m1["policy_set_id"] == m2["policy_set_id"]


def test_cache_invalidates_on_bump() -> None:
    a = get_policy_set_manifest()
    b = get_policy_set_manifest()
    assert a["policy_set_id"] == b["policy_set_id"]
    bump_policy_set_generation()
    c = get_policy_set_manifest()
    assert c["policy_set_id"] == a["policy_set_id"]  # content unchanged
    assert current_policy_set_id() == c["policy_set_id"]
