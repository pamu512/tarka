from author_catalog import IDENTITY_FIELDS, PAYLOAD_FIELDS
from field_registry import (
    apply_field_maps,
    discover_payload,
    merge_registry_rows,
    seed_names,
    validate_registry_name,
)
from fraud_aggregates import _bundled_manifest_feature_outputs, valid_feature_output_rows


def test_seed_has_core_names_not_growth_or_hops():
    names = seed_names()
    assert "event_count_7d" in names
    assert "avg_amount_1h" in names
    assert "amount" in names
    assert "relation_growth_1h" not in names
    assert "USES_DEVICE" not in names


def test_seed_covers_manifest_payload_identity():
    manifest = {r["name"] for r in valid_feature_output_rows(_bundled_manifest_feature_outputs())}
    assert manifest <= seed_names()
    assert set(PAYLOAD_FIELDS) <= seed_names()
    assert set(IDENTITY_FIELDS) <= seed_names()


def test_validate_rejects_tx_prefix_and_bad_shape():
    for bad in ("tx_count_1h", "EventCount", "1h_count", ""):
        try:
            validate_registry_name(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_validate_rejects_legacy_distinct_aliases():
    for bad in ("distinct_devices_24h", "distinct_ips_24h"):
        try:
            validate_registry_name(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_apply_maps_fills_amount_without_clobber():
    out = apply_field_maps({"txn_amt": 9}, [("txn_amt", "amount")])
    assert out["amount"] == 9
    assert out["txn_amt"] == 9
    both = apply_field_maps({"amount": 4, "txn_amt": 9}, [("txn_amt", "amount")])
    assert both["amount"] == 4
    missing = apply_field_maps({"other": 1}, [("txn_amt", "amount")])
    assert "amount" not in missing


def test_apply_maps_copies_present_zero_and_false():
    zero = apply_field_maps({"txn_amt": 0}, [("txn_amt", "amount")])
    assert zero["amount"] == 0
    assert zero["txn_amt"] == 0
    false = apply_field_maps({"is_fraud": False}, [("is_fraud", "fraud_flag")])
    assert false["fraud_flag"] is False
    assert false["is_fraud"] is False


def test_discover_splits_named_mapped_candidates():
    d = discover_payload(
        {"amount": 1, "txn_amt": 1, "order_channel": "web"},
        registry_names={"amount"},
        maps={"txn_amt": "amount"},
    )
    assert d["already_named"] == ["amount"]
    assert d["mapped"] == [{"buyer_key": "txn_amt", "registry_name": "amount"}]
    assert d["candidates"] == [{"buyer_key": "order_channel", "suggested_source": "new_feature"}]


def test_merge_overlay_wins_same_name():
    merged = merge_registry_rows(
        seed=[{"name": "amount", "explanation": "seed", "source": "tarka_core"}],
        overlay=[{"name": "order_channel", "explanation": "who sold", "source": "new_feature"}],
    )
    names = {r["name"] for r in merged}
    assert names == {"amount", "order_channel"}
