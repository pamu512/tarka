"""S0–S2: evidence pack invent-guard and the confidence-gate matrix."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[2] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from jev_system_one.client import SystemOneJudgment  # noqa: E402
from jev_system_one.pack import (  # noqa: E402
    MISSING,
    _text,
    build_evidence_pack,
    is_thin_evidence,
    pack_contains_bait,
)
from jev_system_one.policy import decide_advise, judgment_abstains, preflight_advise
from jev_system_one.questions import PACK_ID

_PASSING = {
    "has_enough_signal": {"value": True, "confidence": 0.9},
    "review_priority": {"value": "routine", "confidence": 0.1},
    "pattern_hint": {"value": "other", "confidence": 0.01},
}


def _answers(*, signal: bool, confidence: float, priority: str) -> dict:
    return {
        "has_enough_signal": {"value": signal, "confidence": confidence},
        "review_priority": {"value": priority, "confidence": 0.99},
        "pattern_hint": {"value": "none", "confidence": 0.01},
    }


def _judgment(answers: dict, *, latency_ms: int = 12) -> SystemOneJudgment:
    return SystemOneJudgment(answers=answers, latency_ms=latency_ms, error=None)


def test_pattern_hint_confidence_does_not_gate() -> None:
    assert judgment_abstains(_PASSING, 0.55) is False


def test_boundary_confidence_is_strict_less_than() -> None:
    assert judgment_abstains(_answers(signal=True, confidence=0.55, priority="routine"), 0.55) is False
    assert judgment_abstains(_answers(signal=True, confidence=0.549, priority="routine"), 0.55) is True


def test_policy_matrix_matches_spec() -> None:
    """Exhaustive gate matrix: signal × confidence × priority × mode, plus errors."""
    min_confidence = 0.55
    for mode in ("shadow", "gate"):
        for signal in (True, False):
            for confidence in (0.0, 0.549, 0.55, 1.0):
                for priority in ("skip_noise", "routine", "urgent"):
                    answers = _answers(signal=signal, confidence=confidence, priority=priority)
                    decision = decide_advise(
                        mode=mode,
                        min_confidence=min_confidence,
                        judgment=_judgment(answers),
                    )
                    abstain = (not signal) or confidence < min_confidence or priority == "skip_noise"
                    assert decision.gate == ("abstain" if abstain else "pass")
                    assert decision.call_llm is (mode == "shadow" or not abstain)
                    assert decision.receipt is not None
                    assert decision.receipt["answers"] == answers
                    assert decision.receipt["llm_invoked"] is decision.call_llm
                    assert decision.receipt["mode"] == mode
                    assert decision.receipt["pack"] == PACK_ID
                    raw = json.dumps(decision.receipt)
                    assert "ALLOW" not in raw
                    assert "DENY" not in raw
                    assert "Promote" not in raw


def test_error_matrix_fail_closed_per_mode() -> None:
    for mode in ("shadow", "gate"):
        for error in ("timeout", "http", "schema", "transport"):
            decision = decide_advise(
                mode=mode,
                min_confidence=0.55,
                judgment=SystemOneJudgment(answers=None, latency_ms=400, error=error),
            )
            assert decision.gate == "jev_error"
            assert decision.receipt is not None
            assert decision.receipt["answers"] is None
            assert decision.call_llm is (mode == "shadow")
            assert decision.receipt["llm_invoked"] is decision.call_llm
            assert decision.call_jev is False


def test_auth_error_is_jev_auth_per_mode() -> None:
    for mode in ("shadow", "gate"):
        decision = decide_advise(
            mode=mode,
            min_confidence=0.55,
            judgment=SystemOneJudgment(answers=None, latency_ms=12, error="auth"),
        )
        assert decision.gate == "jev_auth"
        assert decision.receipt is not None
        assert decision.receipt["gate"] == "jev_auth"
        assert decision.receipt["answers"] is None
        assert decision.call_llm is (mode == "shadow")
        assert decision.receipt["llm_invoked"] is decision.call_llm
        assert decision.call_jev is False
        raw = json.dumps(decision.receipt)
        assert "Bearer" not in raw
        assert "jev-secret" not in raw


def test_required_key_missing_is_preflight_jev_auth() -> None:
    thick = {"leftover": {"case_id": "c1"}, "receipt": {"pack_id": "fintech", "rule_hits": ["v"], "why": "v"}}
    for mode, call_llm in (("shadow", True), ("gate", False)):
        decision = preflight_advise(
            url="http://jev.test",
            mode=mode,
            pack=thick,
            api_key="",
            api_key_required=True,
        )
        assert decision is not None
        assert decision.gate == "jev_auth"
        assert decision.call_jev is False
        assert decision.call_llm is call_llm
        assert decision.receipt is not None
        assert decision.receipt["answers"] is None
        assert decision.receipt["llm_invoked"] is call_llm


def test_blank_key_is_anonymous_when_not_required() -> None:
    thick = {"leftover": {"case_id": "c1"}, "receipt": {"pack_id": "fintech", "rule_hits": ["v"], "why": "v"}}
    decision = preflight_advise(
        url="http://jev.test",
        mode="shadow",
        pack=thick,
        api_key="",
        api_key_required=False,
    )
    assert decision is None


def test_empty_url_and_mode_off_are_todays_path_even_when_thin() -> None:
    for url, mode in (("", "shadow"), ("http://jev.test", "off")):
        decision = preflight_advise(url=url, mode=mode, pack=None)
        assert decision is not None
        assert decision.call_llm is True
        assert decision.call_jev is False
        assert decision.gate == "off"
        assert decision.receipt is None


def test_thin_evidence_skips_jev_and_llm_in_both_modes() -> None:
    for mode in ("shadow", "gate"):
        decision = preflight_advise(url="http://jev.test", mode=mode, pack=None)
        assert decision is not None
        assert decision.gate == "thin_evidence"
        assert decision.call_jev is False
        assert decision.call_llm is False
        assert decision.receipt is not None
        assert decision.receipt["answers"] is None
        assert decision.receipt["llm_invoked"] is False


def test_unknown_mode_and_unknown_pack_do_not_invent_answers() -> None:
    unknown_mode = preflight_advise(url="http://jev.test", mode="judge", pack=None)
    assert unknown_mode is not None
    assert unknown_mode.call_llm is False
    assert unknown_mode.receipt is not None
    assert unknown_mode.receipt["answers"] is None
    thick = {"leftover": {"case_id": "c1"}, "receipt": {"pack_id": MISSING, "rule_hits": [], "why": MISSING}}
    for mode, call_llm in (("shadow", True), ("gate", False)):
        bad_pack = preflight_advise(
            url="http://jev.test",
            mode=mode,
            pack=thick,
            question_pack="other_pack",
        )
        assert bad_pack is not None
        assert bad_pack.gate == "jev_error"
        assert bad_pack.call_llm is call_llm
        assert bad_pack.receipt is not None
        assert bad_pack.receipt["answers"] is None


def test_pii_scan_is_linear_on_percent_soup() -> None:
    """CodeQL 398: no backtracking email regex on unbounded case/audit text."""
    soup = "%" * 20_000
    assert _text(soup) == soup[:128]
    assert _text("person@example.com") == ""
    assert _text("4111 1111 1111 1111") == ""
    pack = build_evidence_pack(
        tenant_id="tenant-a",
        case={"id": soup, "email": "person@example.com"},
        audit={"pack_id": "fintech", "rule_hits": ["velocity_burst"]},
    )
    assert pack["leftover"]["case_id"] == soup[:128]
    assert "person@example.com" not in json.dumps(pack)
    assert "@" not in json.dumps(pack)


def test_why_strip_invent_guard_and_pii_allowlist() -> None:
    bait_ml = "BAIT_ML_SUMMARY_do_not_copy"
    bait_action = "deny the payout immediately"
    email = "person@example.com"
    pack = build_evidence_pack(
        tenant_id="tenant-a",
        case={
            "id": "case-1",
            "tenant_id": "tenant-a",
            "entity_id": "ent-1",
            "trace_id": "trace-1",
            "email": email,
            "title": "Jane Doe",
            "labels": ["late_label"],
        },
        audit={
            "ml_summary": bait_ml,
            "recommended_action": bait_action,
            "decision": "deny",
            "event_type": "card_payment",
            "amount": 80,
            "pack_id": "fintech",
            "rule_hits": ["velocity_burst"],
        },
        graph={
            "edges": [
                {
                    "from_id": "ent-1",
                    "to_id": "dev-9",
                    "type": "USES_DEVICE",
                    "properties": {"email": email, "note": bait_ml},
                }
            ]
        },
    )
    assert pack["receipt"]["why"] == "velocity_burst"
    assert pack["receipt"]["pack_id"] == "fintech"
    assert pack["flags"]["late_label"] is True
    assert pack["hops"] == [{"id": "ent-1->dev-9", "type": "USES_DEVICE"}]
    assert not pack_contains_bait(pack, bait_ml, bait_action, email, "Jane Doe")
    assert is_thin_evidence(pack) is False


def test_missing_why_is_literal_missing_not_invented() -> None:
    pack = build_evidence_pack(
        tenant_id="tenant-a",
        case={"id": "case-1"},
        audit={
            "ml_summary": "looks like a bot",
            "recommended_action": "block",
            "pack_id": "device_signals",
        },
    )
    assert pack["receipt"]["why"] == MISSING
    assert pack["receipt"]["pack_id"] == "device_signals"
    assert "looks like a bot" not in json.dumps(pack)
    assert "block" not in json.dumps(pack["receipt"])


def test_no_case_and_no_receipt_is_thin() -> None:
    pack = build_evidence_pack(tenant_id="tenant-a", case=None, audit=None)
    assert pack["receipt"]["why"] == MISSING
    assert pack["receipt"]["pack_id"] == MISSING
    assert is_thin_evidence(pack) is True


def test_pack_char_cap_drops_hops_before_receipt_ids() -> None:
    hops = [
        {"from_id": f"entity-{i:04d}", "to_id": f"device-{i:04d}-" + ("x" * 80), "type": "USES_DEVICE"}
        for i in range(40)
    ]
    pack = build_evidence_pack(
        tenant_id="tenant-a",
        case={"id": "case-1"},
        audit={"pack_id": "fintech", "rule_hits": ["velocity_burst"]},
        graph={"edges": hops},
    )
    assert len(json.dumps(pack, sort_keys=True, separators=(",", ":"))) <= 4000
    assert pack["receipt"]["pack_id"] == "fintech"
