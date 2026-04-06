from investigation_agent.copilot_hardening import (
    deterministic_claim_support,
    tool_error_acknowledgment_warnings,
)


def test_tool_error_acknowledgment_warnings():
    tcs = [
        {"tool": "get_case", "args": {}, "result": {"error": "not_found"}},
    ]
    w = tool_error_acknowledgment_warnings("All good, case resolved.", tcs)
    assert w
    w2 = tool_error_acknowledgment_warnings("get_case returned an error.", tcs)
    assert not w2


def test_deterministic_claim_support():
    claims = [{"text": "Trace abcdef12-3456-7890-abcd-ef1234567890 was reviewed", "source": "tool"}]
    tcs = [
        {
            "tool": "get_decision_audit",
            "args": {},
            "result": {"audit": {"trace_id": "abcdef12-3456-7890-abcd-ef1234567890"}},
        },
    ]
    out = deterministic_claim_support(claims, tcs)
    assert out[0]["supported"] is True
