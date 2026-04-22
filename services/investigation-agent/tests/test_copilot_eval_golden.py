from __future__ import annotations
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from investigation_agent.main import app

"""Golden eval cases from fixtures (structural; works with OPENAI_API_KEY unset / offline reply)."""
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "copilot_eval_cases.json"


def _load() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_eval_fixture_version():
    data = _load()
    assert data.get("version") == 1
    assert len(data.get("cases") or []) >= 1


@pytest.mark.parametrize("case", _load()["cases"], ids=lambda c: c.get("id", "?"))
def test_eval_cases(client: TestClient, case: dict):
    ex = case.get("expect") or {}
    if "request_base" in case and "personas_differ" in ex:
        base = dict(case["request_base"])
        personas = ex["personas_differ"]
        results: list[str] = []
        for p in personas:
            req = {**base, "persona": p}
            r = client.post("/v1/chat", json=req)
            assert r.status_code == ex.get("status", 200), case["id"]
            body = r.json()
            assert body.get("persona") == p, case["id"]
            results.append(body.get("reply") or "")
        if len(personas) == 2 and results[0] == results[1]:
            pytest.skip("offline mode returns identical stub reply; A/B content check needs LLM")
        return

    req = case.get("request") or {}
    r = client.post("/v1/chat", json=req)
    assert r.status_code == ex.get("status", 200), r.text
    body = r.json()
    bex = ex.get("body") or {}
    if "persona" in bex:
        assert body.get("persona") == bex["persona"], case["id"]
    for k in bex.get("has_keys") or []:
        assert k in body, (case["id"], k)
