"""POST /v1/rules/visual/mermaid — RuleExpr → Mermaid (tarka-core via ``tarka`` PyO3)."""

import sys
import types

import pytest
from httpx import ASGITransport, AsyncClient

from decision_api.main import app


@pytest.fixture
async def asgi_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_rule_expr_mermaid_ok_with_stub_tarka(
    asgi_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEYS", "k")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")

    dec = types.ModuleType("decision")

    def stub(raw: str) -> str:
        assert '"kind"' in raw or "'kind'" in raw
        return "flowchart TD\n    %%stub\n"

    dec.rule_expr_mermaid_flowchart = stub  # type: ignore[attr-defined]
    tarka_mod = types.ModuleType("tarka")
    tarka_mod.decision = dec
    monkeypatch.setitem(sys.modules, "tarka", tarka_mod)
    monkeypatch.setitem(sys.modules, "tarka.decision", dec)

    body = {
        "rule_expr": {
            "kind": "compare_leaf",
            "id": "leaf_a",
            "path": "/amount",
            "op": "gte",
            "expected": 100,
        }
    }
    r = await asgi_client.post(
        "/v1/rules/visual/mermaid",
        headers={"x-api-key": "k"},
        json=body,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["format"] == "mermaid_flowchart_td_v1"
    assert "flowchart TD" in data["mermaid"]


@pytest.mark.asyncio
async def test_rule_expr_mermaid_503_when_tarka_missing(
    asgi_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEYS", "k")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.delitem(sys.modules, "tarka", raising=False)
    monkeypatch.delitem(sys.modules, "tarka.decision", raising=False)

    body = {
        "rule_expr": {
            "kind": "compare_leaf",
            "id": "x",
            "path": "/a",
            "op": "eq",
            "expected": 1,
        }
    }
    r = await asgi_client.post(
        "/v1/rules/visual/mermaid",
        headers={"x-api-key": "k"},
        json=body,
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_rule_expr_mermaid_400_on_bad_json(
    asgi_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEYS", "k")

    dec = types.ModuleType("decision")

    def boom(_raw: str) -> str:
        raise ValueError("invalid RuleExpr JSON: expected")

    dec.rule_expr_mermaid_flowchart = boom  # type: ignore[attr-defined]
    tarka_mod = types.ModuleType("tarka")
    tarka_mod.decision = dec
    monkeypatch.setitem(sys.modules, "tarka", tarka_mod)
    monkeypatch.setitem(sys.modules, "tarka.decision", dec)

    body = {"rule_expr": {"kind": "not_a_real_variant"}}
    r = await asgi_client.post(
        "/v1/rules/visual/mermaid",
        headers={"x-api-key": "k"},
        json=body,
    )
    assert r.status_code == 400
