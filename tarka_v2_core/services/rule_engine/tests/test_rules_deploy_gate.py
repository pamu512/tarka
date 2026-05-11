"""Gate: deploy v2, flip DB to v1 active, reload, evaluation reverts immediately."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_RULE = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_RULE, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rule_engine.main import create_app  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


def _txn(amount: float) -> dict:
    return {
        "entity_id": "99999999-9999-9999-9999-999999999999",
        "amount": amount,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {},
    }


def test_deploy_v2_then_db_activate_v1_reload_reverts_evaluation(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "rules_gate.sqlite"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("RULE_ENGINE_DATABASE_URL", url)

    rule_v1 = {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1",
        "name": "v1_amount_gt_200_shadow",
        "root_node": {
            "field": {"field": "amount"},
            "operator": "GT",
            "value": 200.0,
        },
        "action": "SHADOW_REVIEW",
        "priority": 10,
    }
    rule_v2 = {
        "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2",
        "name": "v2_amount_gt_50_block",
        "root_node": {
            "field": {"field": "amount"},
            "operator": "GT",
            "value": 50.0,
        },
        "action": "BLOCK",
        "priority": 5,
    }

    app = create_app()
    with TestClient(app) as client:
        r1 = client.post("/v1/rules/deploy", json={"rules": [rule_v1]})
        assert r1.status_code == 200, r1.text
        assert r1.json() == {"ok": True, "version": 1, "rule_count": 1}

        r2 = client.post("/v1/rules/deploy", json={"rules": [rule_v2]})
        assert r2.status_code == 200, r2.text
        assert r2.json() == {"ok": True, "version": 2, "rule_count": 1}

        ev_v2 = client.post("/v1/evaluate", json=_txn(100.0))
        assert ev_v2.status_code == 200
        assert ev_v2.json()["actions"] == ["BLOCK"]

        engine = create_engine(url, future=True)
        with engine.begin() as conn:
            conn.execute(text("UPDATE fraud_rules SET is_active = 0"))
            conn.execute(text("UPDATE fraud_rules SET is_active = 1 WHERE version = 1"))
        engine.dispose()

        rel = client.post("/v1/rules/reload")
        assert rel.status_code == 200
        assert rel.json().get("ok") is True

        ev_v1 = client.post("/v1/evaluate", json=_txn(100.0))
        assert ev_v1.status_code == 200
        assert ev_v1.json()["actions"] == []
