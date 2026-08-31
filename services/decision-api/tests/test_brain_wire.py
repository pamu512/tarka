import json

import pytest

from decision_api.brain_wire import HELPFULNESS_DROP, brain_wire_verdict


def _h(*, blockers=(), underpowered=False, labeled=5, tp=0, fp=5):
    return {
        "blockers": list(blockers),
        "underpowered": underpowered,
        "labeled_extras": labeled,
        "extra_tp": tp,
        "extra_fp": fp,
    }


def test_fp_over_cap_drops_and_kills():
    v = brain_wire_verdict(
        _h(blockers=["leftover_extras_fp_over_cap"]),
        {"rules": []},
        proposed_rule_ids=["r1"],
        fp_cap=0.4,
    )
    assert v["publish_allowed"] is False
    assert v["reason"] == "leftover_extras_fp_over_cap"
    assert v["should_kill"] is True


def test_no_lift_drops_and_kills():
    v = brain_wire_verdict(
        _h(blockers=["leftover_extras_no_lift"]),
        {"rules": []},
        proposed_rule_ids=["r1"],
        fp_cap=0.4,
    )
    assert v["reason"] == "leftover_extras_no_lift"
    assert v["should_kill"] is True


def test_sla_cost_blocker_does_not_drop():
    v = brain_wire_verdict(
        _h(blockers=["leftover_sla_breached"], underpowered=True, labeled=0, tp=0, fp=0),
        {"rules": []},
        proposed_rule_ids=["r1"],
        fp_cap=0.4,
    )
    assert v["publish_allowed"] is True
    assert v["should_kill"] is False
    assert v["stamp_underpowered"] is True


def test_rule_fp_strips_then_empty_drops():
    precision = {
        "rules": [
            {"rule_id": "r1", "enough_support": True, "fp_rate": 0.8},
            {"rule_id": "r2", "enough_support": False, "fp_rate": 0.9},
        ]
    }
    v = brain_wire_verdict(_h(underpowered=True, labeled=0), precision, proposed_rule_ids=["r1", "r2"], fp_cap=0.4)
    assert v["keep_rule_ids"] == ["r2"]
    v2 = brain_wire_verdict(_h(underpowered=True, labeled=0), precision, proposed_rule_ids=["r1"], fp_cap=0.4)
    assert v2["publish_allowed"] is False
    assert v2["reason"] == "rule_fp_over_cap"
    assert v2["should_kill"] is False


def test_underpowered_stamps_and_publishes():
    v = brain_wire_verdict(_h(underpowered=True, labeled=3, tp=1, fp=2), {"rules": []}, proposed_rule_ids=["r1"], fp_cap=0.4)
    assert v["publish_allowed"] is True
    assert v["stamp_underpowered"] is True
    assert v["should_kill"] is False


def _write_shadow(rules_dir, filename, *, name, is_ai_authored, authored_by, evidence=None, scout_report_id=""):
    pack = {
        "version": 1,
        "name": name,
        "mode": "shadow",
        "is_ai_authored": is_ai_authored,
        "authored_by": authored_by,
        "rules": [
            {
                "id": "r1",
                "when": [{"field": "amount", "op": "gt", "value": 0}],
                "score_delta": 1.0,
            }
        ],
    }
    if evidence:
        pack["evidence"] = evidence
    if scout_report_id:
        pack["scout_report_id"] = scout_report_id
    (rules_dir / filename).write_text(json.dumps(pack, indent=2), encoding="utf-8")


def test_disable_skips_human_and_slip(tmp_path, monkeypatch):
    from decision_api.brain_wire import disable_ai_shadow_packs, load_killed_fingerprints
    from decision_api.config import settings
    from decision_api.json_rules import load_rules

    rules_dir = tmp_path / "rules"
    data_dir = tmp_path / "data"
    rules_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setattr(settings, "rules_path", str(rules_dir))
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(data_dir))

    _write_shadow(
        rules_dir,
        "ai.json",
        name="ai_draft",
        is_ai_authored=True,
        authored_by="scout_coordinated_burst",
        evidence={"fingerprint_kind": "canvas_hash", "fingerprint_value": "abc123"},
    )
    _write_shadow(
        rules_dir,
        "human.json",
        name="human_canary",
        is_ai_authored=False,
        authored_by="analyst",
    )
    _write_shadow(
        rules_dir,
        "slip.json",
        name="slip_retire_r1",
        is_ai_authored=False,
        authored_by="slip_critic",
    )
    load_rules()

    helpfulness = _h(blockers=["leftover_extras_fp_over_cap"])
    killed = disable_ai_shadow_packs(helpfulness, tenant_id="t1")
    assert "ai.json" in killed
    assert json.loads((rules_dir / "ai.json").read_text(encoding="utf-8"))["mode"] == "disabled"
    assert json.loads((rules_dir / "human.json").read_text(encoding="utf-8"))["mode"] == "shadow"
    assert json.loads((rules_dir / "slip.json").read_text(encoding="utf-8"))["mode"] == "shadow"
    assert ("canvas_hash", "abc123") in load_killed_fingerprints("t1")

    again = disable_ai_shadow_packs(helpfulness, tenant_id="t1")
    assert again == []
    assert json.loads((rules_dir / "human.json").read_text(encoding="utf-8"))["mode"] == "shadow"
    assert json.loads((rules_dir / "slip.json").read_text(encoding="utf-8"))["mode"] == "shadow"


@pytest.mark.asyncio
async def test_maybe_kill_none_computes_with_session(monkeypatch):
    from decision_api.brain_wire import maybe_kill_leftover_fp_shadows

    sentinel = object()
    captured: dict = {}
    disable_ran: dict = {}

    class _CM:
        async def __aenter__(self):
            return sentinel

        async def __aexit__(self, *a):
            return None

    async def fake_compute(tid, draft_id, session=None):
        captured["kwargs"] = {"tid": tid, "draft_id": draft_id, "session": session}
        return {
            "leftover_promote_gate": {
                "helpfulness": _h(blockers=["leftover_extras_fp_over_cap"]),
            }
        }

    def fake_disable(helpfulness, *, tenant_id=""):
        disable_ran["helpfulness"] = helpfulness
        disable_ran["tenant_id"] = tenant_id
        return ["ai.json"]

    monkeypatch.setattr("decision_api.db.SessionLocal", lambda: _CM())
    monkeypatch.setattr(
        "decision_api.leftover_promote_gate.compute_desk_and_leftover_gates",
        fake_compute,
    )
    monkeypatch.setattr("decision_api.brain_wire.disable_ai_shadow_packs", fake_disable)

    killed = await maybe_kill_leftover_fp_shadows("t1", leftover_g=None)
    assert captured["kwargs"]["session"] is sentinel
    assert disable_ran["tenant_id"] == "t1"
    assert "leftover_extras_fp_over_cap" in disable_ran["helpfulness"]["blockers"]
    assert killed == ["ai.json"]
