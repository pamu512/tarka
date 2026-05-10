"""Tests for command-palette rule substring search."""

from decision_api import json_rules as jr
from decision_api.json_rules import search_omni_rules


def test_search_omni_rules_empty_query():
    assert search_omni_rules("", 10) == []
    assert search_omni_rules("   ", 10) == []


def test_search_omni_rules_finds_rule_id():
    prev = list(jr._cached_packs)
    try:
        jr._cached_packs = [
            {
                "version": 1,
                "name": "Demo",
                "_source_file": "demo_pack.json",
                "rules": [{"id": "unique_rule_xyz", "description": "nothing"}],
                "tag_rules": [],
            }
        ]
        hits = search_omni_rules("unique_rule", 10)
        assert len(hits) >= 1
        assert hits[0]["rule_id"] == "unique_rule_xyz"
        assert hits[0]["pack_file"] == "demo_pack.json"
    finally:
        jr._cached_packs = prev
