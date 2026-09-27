"""P3 demo wiring: synth traffic carries SDK behavior packets.

The behavior challenger pack (rules/behavior_challenger_v1.json) lives in
Observe; it only fires on traffic whose device_context.behavior trips
extract_behavior_tags. The operator synth loop must emit such traffic or the
demo never exercises the P3 story.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".." / "scripts" / "oss"))

from synth_loop import SYNTH_CASES, build_evaluate_body  # noqa: E402


def test_synth_cases_include_behavior_packet():
    behavior_cases = [
        c
        for c in SYNTH_CASES
        if isinstance(c.get("body"), dict)
        and isinstance(c["body"].get("device_context"), dict)
        and isinstance(c["body"]["device_context"].get("behavior"), dict)
    ]
    assert behavior_cases, "no synth case carries a device_context.behavior packet"


def test_behavior_case_mints_bot_tags():
    from decision_api.main import extract_behavior_tags

    behavior_cases = [
        c
        for c in SYNTH_CASES
        if isinstance(c.get("body"), dict)
        and isinstance(c["body"].get("device_context"), dict)
        and isinstance(c["body"]["device_context"].get("behavior"), dict)
    ]
    assert behavior_cases
    dc = behavior_cases[0]["body"]["device_context"]
    tags = extract_behavior_tags(dc)
    assert any(t.startswith("behavior:") for t in tags), (
        f"behavior packet in synth case mints no behavior:* tags: {tags}"
    )


def test_build_evaluate_body_preserves_behavior_packet():
    body = build_evaluate_body(0, tenant="demo")
    dc = body.get("device_context") or {}
    assert isinstance(dc.get("behavior"), dict), (
        "build_evaluate_body drops the behavior packet (tick 0 must be the behavior case)"
    )
