"""API gate: list versions and rollback to prior AST snapshot."""

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
from starlette.testclient import TestClient  # noqa: E402


def _rule_v1() -> dict:
    return {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1",
        "name": "v1_amount_gt_200_shadow",
        "root_node": {"field": {"field": "amount"}, "operator": "GT", "value": 200.0},
        "action": "SHADOW_REVIEW",
        "priority": 10,
    }


def _rule_v2() -> dict:
    return {
        "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2",
        "name": "v2_amount_gt_50_block",
        "root_node": {"field": {"field": "amount"}, "operator": "GT", "value": 50.0},
        "action": "BLOCK",
        "priority": 5,
    }


def test_list_and_rollback_versions(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "rollback_api.sqlite"
    monkeypatch.setenv("RULE_ENGINE_DATABASE_URL", f"sqlite+pysqlite:///{db_path}")

    app = create_app()
    with TestClient(app) as client:
        assert client.post("/v1/rules/deploy", json={"rules": [_rule_v1()]}).status_code == 200
        assert client.post("/v1/rules/deploy", json={"rules": [_rule_v2()]}).status_code == 200

        listed = client.get("/v1/rules/versions")
        assert listed.status_code == 200
        body = listed.json()
        assert body["active_version"] == 2
        assert len(body["versions"]) == 2
        assert body["versions"][0]["version"] == 2

        rb = client.post("/v1/rules/rollback/1")
        assert rb.status_code == 200
        assert rb.json()["active_version"] == 1

        listed2 = client.get("/v1/rules/versions")
        assert listed2.json()["active_version"] == 1

        detail = client.get("/v1/rules/versions/1")
        assert detail.status_code == 200
        assert detail.json()["is_active"] is True
        assert detail.json()["rule_count"] == 1
