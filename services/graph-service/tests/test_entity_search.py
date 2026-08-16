from unittest.mock import AsyncMock

from graph_service.entity_risk_score import (
    SEARCH_PROP_KEYS,
    cap_identifier_owners,
    clamp_search_limit,
    cypher_search_prop_predicate,
    eligible_search_node,
    eligible_search_node_prefix,
    matched_on_from_props,
    matched_on_from_props_prefix,
    merge_search_hits,
    search_hit_from_node,
)


def test_clamp_search_limit():
    assert clamp_search_limit(None) == 20
    assert clamp_search_limit(0) == 1
    assert clamp_search_limit(99) == 50
    assert clamp_search_limit(7) == 7


def test_search_hit_unscored_is_null_not_zero():
    hit = search_hit_from_node("t", "a", ["Account"], {})
    assert hit["scored"] is False
    assert hit["risk_score"] is None
    assert hit["labels"] == ["Account"]
    assert hit["matched_on"] == "external_id"
    assert hit["via"] is None


def test_search_hit_scored_zero_is_zero():
    hit = search_hit_from_node(
        "t",
        "a",
        ["Person"],
        {"risk_computed_at": "2026-08-13T00:00:00Z", "risk_score": 0, "risk_factors": []},
    )
    assert hit["scored"] is True
    assert hit["risk_score"] == 0


def test_search_http_empty_q_no_store(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    store = AsyncMock(return_value=([], False))
    monkeypatch.setattr("graph_service.main.search_entities", store)
    from fastapi.testclient import TestClient
    from graph_service.main import app

    with TestClient(app) as client:
        data = client.get("/v1/entities/search", params={"tenant_id": "t"}).json()
    assert data == {"entities": []}
    store.assert_not_called()


def test_search_http_forwards_label_and_limit(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    store = AsyncMock(
        return_value=(
            [
                {
                    "entity_id": "fraud_frank",
                    "tenant_id": "t",
                    "labels": ["Person"],
                    "scored": True,
                    "risk_score": 72,
                }
            ],
            False,
        )
    )
    monkeypatch.setattr("graph_service.main.search_entities", store)
    from fastapi.testclient import TestClient
    from graph_service.main import app

    with TestClient(app) as client:
        data = client.get(
            "/v1/entities/search",
            params={"tenant_id": "t", "q": "frank", "label": "Person", "limit": 999},
        ).json()
    assert data["entities"][0]["entity_id"] == "fraud_frank"
    assert data["truncated"] is False
    store.assert_awaited_once()
    kwargs = store.await_args.kwargs
    assert kwargs["q"] == "frank"
    assert kwargs["label"] == "Person"
    assert kwargs["limit"] == 50


def test_search_http_truncated_true(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    store = AsyncMock(return_value=([], True))
    monkeypatch.setattr("graph_service.main.search_entities", store)
    from fastapi.testclient import TestClient
    from graph_service.main import app

    with TestClient(app) as client:
        data = client.get(
            "/v1/entities/search",
            params={"tenant_id": "t", "q": "x"},
        ).json()
    assert data == {"entities": [], "truncated": True}


def test_matched_on_allowlist_order_strings_only():
    props = {"external_id": "user-441", "email": "alice@acme.com", "device_id": 99}
    assert matched_on_from_props(props, "alice@acme") == "email"
    assert matched_on_from_props(props, "user-441") == "external_id"
    assert matched_on_from_props(props, "99") is None
    assert matched_on_from_props(props, "") is None


def test_eligible_skips_blank_external_id():
    assert eligible_search_node("", {"email": "alice@acme.com"}, "alice") is None
    assert eligible_search_node("  ", {"email": "alice@acme.com"}, "alice") is None
    assert eligible_search_node("e1", {"email": "alice@acme.com"}, "alice") == "email"


def test_merge_resolve_person_first_keeps_email():
    email = search_hit_from_node(
        "t",
        "alice@acme.com",
        ["Email"],
        {"email": "alice@acme.com"},
        matched_on="email",
        via=None,
    )
    person = search_hit_from_node(
        "t",
        "user-441",
        ["Person"],
        {},
        matched_on="email",
        via={"entity_id": "alice@acme.com", "labels": ["Email"]},
    )
    rows = merge_search_hits([email, person], label=None, limit=20)
    assert [h["entity_id"] for h in rows] == ["user-441", "alice@acme.com"]
    assert rows[0]["via"]["entity_id"] == "alice@acme.com"
    assert rows[1]["via"] is None


def test_merge_label_chip_after_resolve():
    email = search_hit_from_node(
        "t",
        "alice@acme.com",
        ["Email"],
        {},
        matched_on="email",
        via=None,
    )
    person = search_hit_from_node(
        "t",
        "user-441",
        ["Person"],
        {},
        matched_on="email",
        via={"entity_id": "alice@acme.com", "labels": ["Email"]},
    )
    only_p = merge_search_hits([email, person], label="Person", limit=20)
    assert [h["entity_id"] for h in only_p] == ["user-441"]
    only_e = merge_search_hits([email, person], label="Email", limit=20)
    assert [h["entity_id"] for h in only_e] == ["alice@acme.com"]
    assert merge_search_hits([email, person], label="Merchant", limit=20) == []


def test_merge_dedupe_keeps_via():
    direct = search_hit_from_node(
        "t",
        "user-441",
        ["Person"],
        {"email": "alice@acme.com"},
        matched_on="email",
        via=None,
    )
    via_hit = search_hit_from_node(
        "t",
        "user-441",
        ["Person"],
        {},
        matched_on="email",
        via={"entity_id": "alice@acme.com", "labels": ["Email"]},
    )
    rows = merge_search_hits([direct, via_hit], label=None, limit=20)
    assert len(rows) == 1
    assert rows[0]["entity_id"] == "user-441"
    assert rows[0]["via"]["entity_id"] == "alice@acme.com"


def test_cap_identifier_owners_fanout_10():
    ident = "dev-1"
    owners = [
        search_hit_from_node(
            "t",
            f"u-{i:02d}",
            ["User"],
            {},
            matched_on="device_id",
            via={"entity_id": ident, "labels": ["Device"]},
        )
        for i in range(12)
    ]
    capped = cap_identifier_owners(owners)
    assert len(capped) == 10
    merged = merge_search_hits(
        [search_hit_from_node("t", ident, ["Device"], {}, matched_on="device_id", via=None)]
        + capped,
        label=None,
        limit=50,
    )
    assert len([h for h in merged if "User" in h["labels"]]) == 10
    assert any(h["entity_id"] == ident for h in merged)


def test_merge_unscored_sorts_after_scored():
    a = search_hit_from_node("t", "z-user", ["User"], {}, matched_on="email")
    b = search_hit_from_node(
        "t",
        "a-user",
        ["User"],
        {"risk_computed_at": "2026-08-13T00:00:00Z", "risk_score": 0},
        matched_on="email",
    )
    rows = merge_search_hits([a, b], label=None, limit=20)
    assert [h["entity_id"] for h in rows] == ["a-user", "z-user"]
    assert rows[0]["risk_score"] == 0
    assert rows[1]["risk_score"] is None


def test_cypher_predicate_uses_frozen_keys_not_q():
    src = cypher_search_prop_predicate("n")
    assert "n.email" in src
    assert "n.device_id" in src
    assert "n.line1" in src
    assert "n.card_id" in src
    assert "toLower($q)" in src
    assert "alice" not in src
    for key in SEARCH_PROP_KEYS:
        assert f"n.{key}" in src


def test_prefix_recheck_drops_non_prefix_lucene_token():
    assert matched_on_from_props_prefix({"email": "user alice@acme.com"}, "alice") is None
    assert matched_on_from_props_prefix({"email": "alice@acme.com"}, "ALICE") == "email"
    assert matched_on_from_props_prefix({"email": "alice@acme.com"}, "lice") is None
    assert matched_on_from_props_prefix({"device_id": 99}, "99") is None
    assert matched_on_from_props_prefix({"email": "alice@acme.com"}, "") is None
    assert matched_on_from_props({"email": "user alice@acme.com"}, "alice") == "email"
    assert eligible_search_node_prefix("", {"email": "alice@acme.com"}, "alice") is None
    assert eligible_search_node_prefix("e1", {"email": "alice@acme.com"}, "alice") == "email"


def test_cap_identifier_owners_dedupes_via_owner_pair():
    ident = "dev-1"
    owners = []
    for i in range(10):
        hit = search_hit_from_node(
            "t",
            f"u-{i:02d}",
            ["User"],
            {},
            matched_on="device_id",
            via={"entity_id": ident, "labels": ["Device"]},
        )
        owners.append(hit)
        owners.append(dict(hit))
    owners.extend(
        [
            search_hit_from_node(
                "t",
                f"extra-{i}",
                ["User"],
                {},
                matched_on="device_id",
                via={"entity_id": ident, "labels": ["Device"]},
            )
            for i in range(2)
        ]
    )
    capped = cap_identifier_owners(owners)
    assert len(capped) == 10
    assert [h["entity_id"] for h in capped] == [f"u-{i:02d}" for i in range(10)]
