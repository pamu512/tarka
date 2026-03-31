from decision_api.simulation_api import _eval_with_override_rules
from decision_api.vertical_packs import get_vertical_pack, list_vertical_packs


def test_vertical_pack_catalog_contains_expected():
    catalog = list_vertical_packs()
    assert "fintech" in catalog
    assert "ecommerce" in catalog
    assert "gaming" in catalog


def test_vertical_pack_rules_apply():
    pack = get_vertical_pack("fintech")
    assert pack is not None
    event = {
        "payload": {
            "amount": 3000,
            "account_age_days": 5,
            "transaction_count_24h": 2,
        }
    }
    out = _eval_with_override_rules(event, pack["rules"])
    assert out["decision"] in {"allow", "review", "deny"}
    assert len(out["rule_hits"]) >= 1
