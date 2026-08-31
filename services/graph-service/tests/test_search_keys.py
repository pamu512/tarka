import pytest

from graph_service.search_keys import (
    keys_from_upsert,
    normalize_search_key,
    outcome_rank,
    sort_search_hits,
)


def test_normalize_and_person_keys():
    assert normalize_search_key("  Alice@Acme.com ") == "alice@acme.com"
    keys = keys_from_upsert("Person", "user-441", {"email": "Alice@Acme.com", "phone": "555-0100"})
    assert ("email", "alice@acme.com") in keys
    assert ("external_id", "user-441") in keys
    assert keys_from_upsert("Device", "dev-1", {"email": "x@y.com"}) == [("external_id", "dev-1")]


def test_outcome_rank_unknown_between_flag_and_allow():
    assert outcome_rank("deny") < outcome_rank("review") < outcome_rank("flag")
    assert outcome_rank(None) > outcome_rank("flag")
    assert outcome_rank(None) < outcome_rank("allow")
    assert outcome_rank("") == outcome_rank(None)


def test_sort_dedupe_person_wins_device():
    hits = [
        {
            "entity_external_id": "user-441",
            "key_kind": "external_id",
            "labels": ["Device"],
            "last_outcome": "allow",
        },
        {
            "entity_external_id": "user-441",
            "key_kind": "email",
            "labels": ["Person"],
            "last_outcome": "deny",
        },
        {
            "entity_external_id": "other",
            "key_kind": "email",
            "labels": ["Person"],
            "last_outcome": None,
        },
    ]
    rows = sort_search_hits(hits, limit=20)
    assert [r["entity_id"] for r in rows] == ["user-441", "other"]
    assert rows[0]["last_outcome"] == "deny"


@pytest.mark.asyncio
async def test_age_search_uses_sql_prefix_not_scan(monkeypatch):
    from graph_service import age_client

    hits = ([{"entity_id": "user-441", "key_kind": "email"}], False)

    async def _prefix(tenant_id, q, label=None, limit=20):
        assert tenant_id == "acme"
        assert q == "ali"
        return hits

    async def _scan(*a, **k):
        raise AssertionError("scan fallback must not run when prefix works")

    monkeypatch.setattr("graph_service.search_keys.search_prefix", _prefix)
    monkeypatch.setattr(age_client, "_search_entities_scan_fallback", _scan)
    assert await age_client.search_entities("acme", "ali") == hits
