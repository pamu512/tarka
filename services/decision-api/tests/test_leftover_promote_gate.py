import pytest

from decision_api.leftover_promote_gate import (
    extra_leftover_mint_count,
    extra_review_or_deny_rows,
    fetch_leftover_list,
    fetch_promote_ack,
    leftover_helpfulness,
    leftover_promote_gate,
    mapped_cc_decision_rows,
)


def test_allow_to_review_is_extra_deny_to_review_is_not():
    rows = [
        {"trace_id": "t1", "entity_id": "e1", "champion_decision": "allow", "challenger_decision": "review"},
        {"trace_id": "t2", "entity_id": "e2", "champion_decision": "deny", "challenger_decision": "review"},
        {"trace_id": "t3", "entity_id": "e3", "champion_decision": "flag", "challenger_decision": "deny"},
    ]
    extras = extra_review_or_deny_rows(rows)
    assert {r["trace_id"] for r in extras} == {"t1", "t3"}
    assert extra_leftover_mint_count(extras, mint_on=True) == 2
    assert extra_leftover_mint_count(extras, mint_on=False) == 0


def test_helpfulness_fp_over_cap_and_underpowered():
    extras = [
        {"trace_id": f"t{i}", "entity_id": f"e{i}", "champion_decision": "allow", "challenger_decision": "review"}
        for i in range(5)
    ]
    by_trace = {f"t{i}": "0" for i in range(5)}
    h = leftover_helpfulness(extras, by_trace=by_trace, by_entity={}, min_labeled_extras=5, fp_rate_cap=0.4)
    assert h["labeled_extras"] == 5
    assert h["extra_fp"] == 5
    assert h["extra_tp"] == 0
    assert h["fp_rate"] == 1.0
    assert h["underpowered"] is False
    assert "leftover_extras_fp_over_cap" in h["blockers"]
    assert "leftover_extras_no_lift" in h["blockers"]

    h2 = leftover_helpfulness(extras[:3], by_trace={"t0": "0", "t1": "0", "t2": "0"}, by_entity={})
    assert h2["underpowered"] is True
    assert h2["blockers"] == []


def test_helpfulness_tp_does_not_block_and_proxy_ignored():
    extras = [
        {"trace_id": f"t{i}", "entity_id": f"e{i}", "champion_decision": "allow", "challenger_decision": "review"}
        for i in range(5)
    ]
    by_trace = {f"t{i}": "1" for i in range(5)}
    h = leftover_helpfulness(extras, by_trace=by_trace, by_entity={})
    assert h["extra_tp"] == 5
    assert h["blockers"] == []
    h3 = leftover_helpfulness(extras, by_trace={"t0": "proxy"}, by_entity={})
    assert h3["labeled_extras"] == 0
    assert h3["underpowered"] is True


def test_gate_fail_closed_when_leftovers_unavailable():
    g = leftover_promote_gate(
        leftovers=None,
        extras=[],
        mint_on=False,
        add_cap=10,
        helpfulness=leftover_helpfulness([], by_trace={}, by_entity={}),
        ack=None,
        draft_id="d1",
    )
    assert g["promote_allowed"] is False
    assert "leftover_queue_unavailable" in g["blockers"]


def test_gate_sla_volume_ack_and_empty_green():
    sla = [{"sla_breached": True, "claimed_by": None}]
    g = leftover_promote_gate(
        leftovers=sla,
        extras=[],
        mint_on=True,
        add_cap=10,
        helpfulness=leftover_helpfulness([], by_trace={}, by_entity={}),
        ack=None,
        draft_id="d1",
    )
    assert "leftover_sla_breached" in g["blockers"]

    extras = [{"trace_id": f"t{i}", "champion_decision": "allow", "challenger_decision": "review"} for i in range(11)]
    g2 = leftover_promote_gate(
        leftovers=[],
        extras=extras,
        mint_on=True,
        add_cap=10,
        helpfulness=leftover_helpfulness(extras, by_trace={}, by_entity={}),
        ack=None,
        draft_id="d1",
    )
    assert "leftover_add_over_cap" in g2["blockers"]
    assert g2["extra_leftover_mint"] == 11

    claimed = [{"sla_breached": False, "claimed_by": "ana-a"}]
    g3 = leftover_promote_gate(
        leftovers=claimed,
        extras=[],
        mint_on=False,
        add_cap=10,
        helpfulness=leftover_helpfulness([], by_trace={}, by_entity={}),
        ack=None,
        draft_id="d1",
    )
    assert "leftover_claimer_ack_required" in g3["blockers"]
    g4 = leftover_promote_gate(
        leftovers=claimed,
        extras=[],
        mint_on=False,
        add_cap=10,
        helpfulness=leftover_helpfulness([], by_trace={}, by_entity={}),
        ack={"draft_id": "d1", "acked_by": "ana-a", "acked_at": "t"},
        draft_id="d1",
    )
    assert g4["promote_allowed"] is True

    g5 = leftover_promote_gate(
        leftovers=[],
        extras=[],
        mint_on=False,
        add_cap=10,
        helpfulness=leftover_helpfulness([], by_trace={}, by_entity={}),
        ack=None,
        draft_id=None,
    )
    assert g5["promote_allowed"] is True
    assert g5["ack_required"] is False


def test_mapped_cc_rows_not_capped_at_fifty():
    audits = [
        {
            "trace_id": f"t{i}",
            "entity_id": f"e{i}",
            "payload_snapshot": {
                "policy_routing": {
                    "champion_decision": "allow",
                    "challenger_decision": "review",
                }
            },
        }
        for i in range(60)
    ]
    extras = extra_review_or_deny_rows(mapped_cc_decision_rows(audits))
    assert len(extras) == 60
    assert extras[59]["entity_id"] == "e59"


@pytest.mark.asyncio
async def test_fetch_promote_ack_none_without_tenant_url_or_draft(monkeypatch):
    monkeypatch.setattr("decision_api.config.settings.case_api_url", "http://case.test")
    assert await fetch_promote_ack("", "d1") is None
    assert await fetch_promote_ack("t1", "") is None
    assert await fetch_promote_ack("t1", "  ") is None
    monkeypatch.setattr("decision_api.config.settings.case_api_url", "")
    assert await fetch_promote_ack("t1", "d1") is None


@pytest.mark.asyncio
async def test_fetch_promote_ack_none_on_non_2xx_and_exception(monkeypatch):
    monkeypatch.setattr("decision_api.config.settings.case_api_url", "http://case.test")

    class _Resp:
        status_code = 404

        def json(self):
            return {"ack": {"acked_by": "ana"}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr("decision_api.leftover_promote_gate.httpx.AsyncClient", _Client)
    assert await fetch_promote_ack("t1", "d1") is None

    class _Boom(_Client):
        async def get(self, *a, **k):
            raise RuntimeError("down")

    monkeypatch.setattr("decision_api.leftover_promote_gate.httpx.AsyncClient", _Boom)
    assert await fetch_promote_ack("t1", "d1") is None


def _leftover_list_client(body: dict):
    class _Resp:
        status_code = 200

        def json(self):
            return body

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp()

    return _Client


@pytest.mark.asyncio
async def test_fetch_leftover_list_none_when_truncated(monkeypatch):
    monkeypatch.setattr("decision_api.config.settings.case_api_url", "http://case.test")
    monkeypatch.setattr(
        "decision_api.leftover_promote_gate.httpx.AsyncClient",
        _leftover_list_client(
            {"leftovers": [{"sla_breached": False}], "truncated": True}
        ),
    )
    assert await fetch_leftover_list("t1") is None


@pytest.mark.asyncio
async def test_fetch_leftover_list_returns_rows_when_truncated_false(monkeypatch):
    monkeypatch.setattr("decision_api.config.settings.case_api_url", "http://case.test")
    rows = [{"sla_breached": False, "id": "lo1"}]
    monkeypatch.setattr(
        "decision_api.leftover_promote_gate.httpx.AsyncClient",
        _leftover_list_client({"leftovers": rows, "truncated": False}),
    )
    assert await fetch_leftover_list("t1") == rows


@pytest.mark.asyncio
async def test_fetch_leftover_list_empty_when_truncated_key_missing(monkeypatch):
    monkeypatch.setattr("decision_api.config.settings.case_api_url", "http://case.test")
    monkeypatch.setattr(
        "decision_api.leftover_promote_gate.httpx.AsyncClient",
        _leftover_list_client({"leftovers": []}),
    )
    assert await fetch_leftover_list("t1") == []
