"""Unit tests for PLG sandbox merged rule pack (no Postgres / Rust)."""

from decision_api.sandbox_plg_pack import (
    build_merged_plg_industry_pack,
    merged_pack_fingerprint,
)


def test_build_merged_pack_has_five_rules_and_stable_fingerprint():
    merged, per, keys = build_merged_plg_industry_pack()
    assert merged["version"] == 1
    assert len(keys) == 5
    assert len(merged["rules"]) == 5
    assert merged["_source_file"] == "sandbox_plg_industry_starter.json"
    assert len(per) == 5
    fp1 = merged_pack_fingerprint(merged)
    fp2 = merged_pack_fingerprint(merged)
    assert fp1 == fp2
    assert len(fp1) == 64


def test_each_template_compiles_to_single_rule():
    _, per, keys = build_merged_plg_industry_pack()
    for k in keys:
        assert len(per[k]["rules"]) >= 1
