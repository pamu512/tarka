from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "scripts" / "seed_demo_data.py"


def _load():
    spec = importlib.util.spec_from_file_location("seed_demo_data", SEED)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_tenant_and_mule_counterparty_and_no_direct_graph_posts():
    mod = _load()
    text = SEED.read_text()
    assert mod.TENANT_ID == "demo"
    assert not hasattr(mod, "seed_graph")
    assert "/v1/entities" not in text
    assert "/v1/links" not in text
    txns = mod._mule_transactions()
    assert txns
    frank = [t for t in txns if t["entity_id"] == "fraud_frank"]
    gina = [t for t in txns if t["entity_id"] == "fraud_gina"]
    assert frank and {t["payload"]["counterparty_entity_id"] for t in frank} == {"mule_ivan"}
    assert gina and {t["payload"]["counterparty_entity_id"] for t in gina} == {"mule_jane"}
    for txn in txns:
        assert txn["tenant_id"] == "demo"
        assert txn["entity_id"] != txn["payload"]["counterparty_entity_id"]
        assert "amount" in txn["payload"]
        assert txn["payload"]["currency"] == "USD"
    fraud = mod._fraudster_transactions()
    shared = [
        t for t in fraud
        if t["entity_id"] in {"fraud_frank", "fraud_gina"}
    ]
    assert shared
    assert {t["device_context"]["device_id"] for t in shared} == {"dev_emulator_003"}


def test_require_seed_planes_exits_without_decision_or_graph():
    mod = _load()
    with pytest.raises(SystemExit) as denied:
        mod.require_seed_planes(decision_ok=False, graph_ok=True)
    assert denied.value.code == 1
    with pytest.raises(SystemExit) as no_graph:
        mod.require_seed_planes(decision_ok=True, graph_ok=False)
    assert no_graph.value.code == 1
    mod.require_seed_planes(decision_ok=True, graph_ok=True)


def test_decision_url_default_stays_unprefixed():
    text = SEED.read_text()
    assert 'default="http://localhost:8000"' in text
    assert "--tenant" not in text


def test_demo_cold_path_seeds_and_product_does_not():
    desk = (ROOT / "scripts" / "oss" / "up_desk.sh").read_text()
    product = (ROOT / "scripts" / "oss" / "up_product.sh").read_text()
    assert "seed_demo_data.py" not in product
    assert desk.count("seed_demo_data.py") == 1
    seed_at = desk.index("seed_demo_data.py")
    first_walk = desk.index("walk_receipts.py")
    assert first_walk < seed_at
    assert desk.index("walk_receipts.py", seed_at) > seed_at
    assert '--decision-url "http://127.0.0.1:${CORE_PORT}/decisions"' in desk
    assert '--graph-url "http://127.0.0.1:${GRAPH_PORT}"' in desk
