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
    assert keys == [("external_id", "user-441")]
    assert keys_from_upsert("Device", "dev-1", {"email": "x@y.com"}) == [("external_id", "dev-1")]


def test_identifier_vertices_own_search_keys():
    """Mailbox / phone search hits the instrument, not the latest Person."""
    assert keys_from_upsert("Email", "email:alice@acme.com", {"email": "Alice@Acme.com"}) == [
        ("external_id", "email:alice@acme.com"),
        ("email", "alice@acme.com"),
    ]
    assert keys_from_upsert("Phone", "phone:+15550199", {"phone": "+15550199"}) == [
        ("external_id", "phone:+15550199"),
        ("phone", "+15550199"),
    ]
    assert keys_from_upsert("Document", "passport-9", {}) == [("external_id", "passport-9")]
    assert keys_from_upsert("Card", "card:cardtok-1", {"card_id": "cardtok-1"}) == [
        ("external_id", "card:cardtok-1"),
        ("card_id", "cardtok-1"),
    ]
    assert keys_from_upsert("Address", "addr:12 oak st", {"address": "12 Oak St"}) == [
        ("external_id", "addr:12 oak st"),
        ("address", "12 oak st"),
    ]


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
async def test_search_entities_uses_prefix_not_scan(monkeypatch):
    from graph_service import age_client

    async def _prefix(*_a, **_k):
        return ([{"entity_id": "user-441"}], True)

    scanned: list[int] = []

    async def _scan(*_a, **_k):
        scanned.append(1)
        return [], False

    monkeypatch.setattr("graph_service.search_keys.search_prefix", _prefix)
    monkeypatch.setattr(age_client, "_search_entities_scan_fallback", _scan)
    rows, ok = await age_client.search_entities("demo", "alice")
    assert ok is True
    assert rows == [{"entity_id": "user-441"}]
    assert scanned == []
