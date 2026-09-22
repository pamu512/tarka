import pytest
from decision_api.simulation_api import _eval_with_override_rules
from decision_api.vertical_packs import get_vertical_pack, list_vertical_packs


def test_vertical_pack_catalog_contains_expected():
    catalog = list_vertical_packs()
    assert "fintech" in catalog
    assert "ecommerce" in catalog
    assert "gaming" in catalog


@pytest.mark.parametrize(
    ("vertical_name", "event_payload"),
    [
        (
            "fintech",
            {
                "amount": 3000,
                "account_age_days": 5,
                "transaction_count_24h": 2,
            },
        ),
        (
            "ecommerce",
            {
                "is_bot": True,
                "amount": 250,
                "distinct_countries_7d": 1,
                "transaction_count_24h": 2,
            },
        ),
        (
            "gaming",
            {
                "is_emulator": True,
                "is_bot": True,
                "hour_of_day": 2,
                "transaction_count_24h": 3,
            },
        ),
    ],
)
def test_vertical_pack_rules_apply(vertical_name: str, event_payload: dict):
    pack = get_vertical_pack(vertical_name)
    assert pack is not None
    event = {"payload": event_payload}
    out = _eval_with_override_rules(event, pack["rules"])
    assert out["decision"] in {"allow", "review", "deny"}
    assert len(out["rule_hits"]) >= 1


async def test_get_vertical_pack_route_serves_full_definition():
    """R1c wizard preview: GET /v1/rules/vertical-packs/{name} must serve the
    full pack (rules/tag_rules/kill_criteria), analyst-readable."""
    import httpx
    from unittest.mock import AsyncMock, patch

    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.rule_api.get_vertical_pack") as mock_get:
            mock_get.side_effect = lambda name: (
                get_vertical_pack(name) if name == "fintech" else None
            )
            from decision_api.main import app

            transport = httpx.ASGITransport(app=app)

            async def _call():
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                    r = await c.get("/v1/rules/vertical-packs/fintech")
                    r404 = await c.get("/v1/rules/vertical-packs/not-a-vertical")
                return r, r404

            r, r404 = await _call()
            assert r.status_code == 200
            body = r.json()
            assert body["id"] == "fintech"
            assert isinstance(body["rules"], list) and body["rules"], "rules must be previewable"
            assert "kill_criteria" in body
            # unknown vertical: honest 404, not an empty 200
            assert r404.status_code == 404
