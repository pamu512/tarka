"""L3 ops ledger — fail-closed arm/sign; sim cannot advance."""

from __future__ import annotations

from decision_api.host_action_log import append_host_action, count_actions
from decision_api.l3_ops_ledger import arm_ledger, load_ledger, public_view, sign_week


def test_default_not_started(tmp_path, monkeypatch):
    monkeypatch.setenv("TARKA_L3_OPS_LEDGER_PATH", str(tmp_path / "ledger.json"))
    view = public_view()
    assert view["status"] == "NOT_STARTED"
    assert view["claim_allowed"] is False


def test_arm_rejects_demo_tenant(tmp_path, monkeypatch):
    monkeypatch.setenv("TARKA_L3_OPS_LEDGER_PATH", str(tmp_path / "ledger.json"))
    out = arm_ledger(
        tenant_id="demo",
        week1_start_utc="2026-08-07",
        host_action_sink="internal:jsonl:/tmp/x",
        shadow_evaluate_enabled=True,
        actor="op",
    )
    assert out["ok"] is False
    assert "tenant_id_must_be_named_live_tenant" in out["blockers"]


def test_arm_rejects_sim_sink(tmp_path, monkeypatch):
    monkeypatch.setenv("TARKA_L3_OPS_LEDGER_PATH", str(tmp_path / "ledger.json"))
    out = arm_ledger(
        tenant_id="acme-prod",
        week1_start_utc="2026-08-07",
        host_action_sink="sim:shadow_four_week_sim",
        shadow_evaluate_enabled=True,
        actor="op",
    )
    assert out["ok"] is False
    assert "host_action_sink_cannot_be_sim" in out["blockers"]


def test_arm_and_sign_week1(tmp_path, monkeypatch):
    monkeypatch.setenv("TARKA_L3_OPS_LEDGER_PATH", str(tmp_path / "ledger.json"))
    out = arm_ledger(
        tenant_id="acme-prod",
        week1_start_utc="2026-08-07",
        host_action_sink="internal:jsonl:/tmp/host.jsonl",
        shadow_evaluate_enabled=True,
        actor="op",
    )
    assert out["ok"] is True
    assert out["ledger"]["status"] == "ARMED"
    signed = sign_week(
        week=1,
        checklist={
            "shadow_on": True,
            "host_actions_logged": True,
            "outcomes_joined": True,
            "weekly_metrics": True,
            "sign_off": True,
        },
        actor="op",
    )
    assert signed["ok"] is True
    assert load_ledger()["status"] == "IN_PROGRESS"
    assert load_ledger()["weeks"]["1"]["sign_off"] is True


def test_week4_requires_ece(tmp_path, monkeypatch):
    monkeypatch.setenv("TARKA_L3_OPS_LEDGER_PATH", str(tmp_path / "ledger.json"))
    arm_ledger(
        tenant_id="acme-prod",
        week1_start_utc="2026-08-07",
        host_action_sink="https://ops.example/host-actions",
        shadow_evaluate_enabled=True,
        actor="op",
    )
    for w in (1, 2, 3):
        assert sign_week(
            week=w,
            checklist={
                "shadow_on": True,
                "host_actions_logged": True,
                "outcomes_joined": True,
                "weekly_metrics": True,
                "sign_off": True,
            },
            actor="op",
        )["ok"]
    bad = sign_week(
        week=4,
        checklist={
            "shadow_on": True,
            "host_actions_logged": True,
            "outcomes_joined": True,
            "weekly_metrics": True,
            "ece_candidate": False,
            "sign_off": True,
        },
        actor="op",
    )
    assert bad["ok"] is False
    assert any("ece" in b for b in bad["blockers"])
    good = sign_week(
        week=4,
        checklist={
            "shadow_on": True,
            "host_actions_logged": True,
            "outcomes_joined": True,
            "weekly_metrics": True,
            "ece_candidate": True,
            "sign_off": True,
        },
        actor="op",
    )
    assert good["ok"] is True
    assert load_ledger()["status"] == "COMPLETE"
    assert public_view()["claim_allowed"] is True


def test_host_action_log(tmp_path, monkeypatch):
    monkeypatch.setenv("TARKA_HOST_ACTION_LOG_PATH", str(tmp_path / "actions.jsonl"))
    append_host_action(tenant_id="acme-prod", action="challenge_issued", entity_id="e1")
    append_host_action(tenant_id="other", action="allow")
    assert count_actions("acme-prod") == 1
    assert count_actions() == 2
