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


@pytest.mark.asyncio
async def test_search_prefix_hydrates_stored_risk(monkeypatch):
    """Search hits must carry stored AGE risk (spec sentinel), not hardcoded None."""
    from graph_service import search_keys as sk

    rows = [
        {
            "entity_external_id": "bp-0",
            "entity_type": "Person",
            "key_kind": "person",
            "last_outcome": None,
        },
        {
            "entity_external_id": "bp-9",
            "entity_type": "Person",
            "key_kind": "person",
            "last_outcome": None,
        },
    ]

    class _Conn:
        async def fetch(self, q, *a):
            if "search_keys" in q:
                return rows
            # AGE hydration rows: bp-0 scored 40, bp-9 unscored (null)
            return [
                {"eid": '"bp-0"', "score": "40"},
                {"eid": '"bp-9"', "score": "null"},
            ]

    class _Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *_a):
            return False

    async def _acquire():
        return _Pool()

    async def _get_age_pool():
        return _Pool()

    async def _ensure():
        return None

    from graph_service import age_client

    monkeypatch.setattr(age_client, "get_pool", _get_age_pool)
    monkeypatch.setattr(sk, "_acquire", _acquire)
    monkeypatch.setattr(sk, "ensure_search_keys_table", _ensure)

    hits, truncated = await sk.search_prefix("t1", "bp-", limit=5)
    assert truncated is False
    by_id = {h["entity_id"]: h for h in hits}
    assert by_id["bp-0"]["scored"] is True
    assert by_id["bp-0"]["risk_score"] == 40.0
    assert by_id["bp-9"]["scored"] is False
    assert by_id["bp-9"]["risk_score"] is None
