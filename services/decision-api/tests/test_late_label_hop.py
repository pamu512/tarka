"""Late-label hop: processor webhook binds dispute.outcome to the evaluate snapshot.

Does not reconstruct features. Does not open a desk inbox.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tarka_request_signature import build_signature_headers

from decision_api.gnn_loop.export import export_labeled_rows
from decision_api.gnn_loop.receipts import append_receipt, load_receipts
from decision_api.late_label_api import router as late_label_router
from decision_api.request_signature_middleware import RequestSignatureMiddleware
from decision_api.y_label_store import load_label_records

_SECRET = "late-label-unit-secret"
_PATH = "/v1/webhooks/late-label"


def _snap(*, suffix: str = "a") -> dict:
    return {
        "schema_id": "tarka.gnn_receipt/v1",
        "status": "graph:ok",
        "tenant_id": "acme",
        "trace_id": f"t-{suffix}",
        "entity_id": f"buyer-{suffix}",
        "user_id": f"buyer-{suffix}",
        "role": "buyer",
        "vertices": [
            {"id": f"buyer-{suffix}", "kind": "user", "role": "buyer", "vtype": "user"},
            {
                "id": f"dev-{suffix}",
                "kind": "bridge",
                "role": "device",
                "vtype": "device",
            },
        ],
        "edges": [
            {
                "from_id": f"buyer-{suffix}",
                "to_id": f"dev-{suffix}",
                "type": "USED",
                "src": f"buyer-{suffix}",
                "dst": f"dev-{suffix}",
            }
        ],
    }


def _body(
    *, tenant: str = "acme", trace_id: str = "t-a", outcome: str = "FRAUD"
) -> dict:
    return {
        "tenant_id": tenant,
        "trace_id": trace_id,
        "dispute": {"outcome": outcome},
    }


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REQUEST_SIGNATURE_SECRET", _SECRET)
    app = FastAPI()
    app.add_middleware(
        RequestSignatureMiddleware,
        secret=_SECRET,
        path_prefixes=(_PATH,),
    )
    app.include_router(late_label_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _post(client: AsyncClient, payload: dict, *, signed: bool = True):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json"}
    if signed:
        headers.update(build_signature_headers(raw, secret=_SECRET))
    return await client.post(_PATH, content=raw, headers=headers)


@pytest.mark.asyncio
async def test_webhook_binds_to_existing_receipt(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    snap = _snap(suffix="a")
    append_receipt("acme", snap)

    r = await _post(client, _body(trace_id="t-a", outcome="FRAUD"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["snapshot_bound"] is True
    assert body["trainable"] is True
    assert body["y_label"] == "1"
    assert body["chargeback_class"] == "FRAUD"

    stored_receipts = load_receipts("acme")
    assert len(stored_receipts) == 1
    assert stored_receipts[0]["vertices"] == snap["vertices"]
    assert stored_receipts[0]["edges"] == snap["edges"]

    records = load_label_records("acme")
    assert records["by_trace"]["t-a"] == "1"
    assert records["chargeback_class_by_trace"]["t-a"] == "FRAUD"
    assert records["dispute_outcome_by_trace"]["t-a"] == "FRAUD"


@pytest.mark.asyncio
async def test_missing_receipt_does_not_invent_a_graph(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    r = await _post(client, _body(trace_id="t-ghost", outcome="FRAUD"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["snapshot_bound"] is False
    assert body["trainable"] is False
    assert body["y_label"] == "1"

    receipts = load_receipts("acme")
    assert receipts == [] or all(
        not (row.get("vertices") or row.get("edges")) for row in receipts
    )
    records = load_label_records("acme")
    assert records["by_trace"]["t-ghost"] == "1"
    assert records["chargeback_class_by_trace"]["t-ghost"] == "FRAUD"

    rows = export_labeled_rows("acme", receipts)
    assert len(rows) == 1
    assert rows[0]["y_label"] == "1"
    assert rows[0]["trainable"] is False
    snap = rows[0]["subgraph_snapshot"]
    assert snap.get("edges") in ([], None)
    assert snap.get("vertices") in ([], None)


@pytest.mark.asyncio
async def test_outcome_enum_refused_if_unsigned(client):
    r = await _post(client, _body(outcome="FRAUD"), signed=False)
    assert r.status_code == 401
    assert load_label_records("acme")["by_trace"] == {}


@pytest.mark.asyncio
async def test_invalid_outcome_enum_refused_even_when_signed(client):
    r = await _post(client, _body(outcome="MAYBE"))
    assert r.status_code == 400
    assert load_label_records("acme")["by_trace"] == {}


@pytest.mark.asyncio
async def test_fraud_and_friendly_both_persist(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    append_receipt("acme", _snap(suffix="fraud"))
    append_receipt("acme", _snap(suffix="friend"))

    fraud = await _post(client, _body(trace_id="t-fraud", outcome="FRAUD"))
    friendly = await _post(client, _body(trace_id="t-friend", outcome="FRIENDLY"))
    assert fraud.status_code == 200, fraud.text
    assert friendly.status_code == 200, friendly.text
    assert fraud.json()["y_label"] == "1"
    assert friendly.json()["y_label"] == "0"
    assert friendly.json()["chargeback_class"] == "FRIENDLY"

    records = load_label_records("acme")
    assert records["by_trace"]["t-fraud"] == "1"
    assert records["by_trace"]["t-friend"] == "0"
    assert records["chargeback_class_by_trace"]["t-fraud"] == "FRAUD"
    assert records["chargeback_class_by_trace"]["t-friend"] == "FRIENDLY"
    assert records["dispute_outcome_by_trace"]["t-friend"] == "FRIENDLY"


@pytest.mark.asyncio
async def test_evaluation_token_binds_to_receipt_trace_id(
    client, tmp_path, monkeypatch
):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    append_receipt("acme", _snap(suffix="tok"))
    r = await _post(
        client,
        {
            "tenant_id": "acme",
            "evaluation_token": "t-tok",
            "dispute": {"outcome": "SERVICE"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["snapshot_bound"] is True
    assert body["trace_id"] == "t-tok"
    assert body["y_label"] == "0"
    assert body["chargeback_class"] == "SERVICE"
    rows = export_labeled_rows("acme", load_receipts("acme"))
    assert len(rows) == 1
    assert rows[0]["trace_id"] == "t-tok"
    assert rows[0]["y_label"] == "0"
    assert rows[0]["trainable"] is True
    assert rows[0]["subgraph_snapshot"]["edges"][0]["type"] == "USED"


@pytest.mark.asyncio
async def test_export_sees_joined_y_label(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    append_receipt("acme", _snap(suffix="join"))
    r = await _post(client, _body(trace_id="t-join", outcome="FRIENDLY"))
    assert r.status_code == 200, r.text

    rows = export_labeled_rows("acme", load_receipts("acme"))
    assert len(rows) == 1
    assert rows[0]["trace_id"] == "t-join"
    assert rows[0]["y_label"] == "0"
    assert rows[0]["dispute_outcome"] == "FRIENDLY"
    assert rows[0]["chargeback_class"] == "FRIENDLY"
    assert rows[0]["trainable"] is True
    assert rows[0]["subgraph_snapshot"]["edges"][0]["type"] == "USED"


def test_no_new_desk_inbox_route():
    paths = []
    for route in late_label_router.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        paths.append((frozenset(methods), path))
        lowered = path.lower()
        assert "inbox" not in lowered
        assert "queue" not in lowered
        assert "disputes" not in lowered
        assert "crm" not in lowered
        assert "cases" not in lowered
    assert paths == [(frozenset({"POST"}), _PATH)]
