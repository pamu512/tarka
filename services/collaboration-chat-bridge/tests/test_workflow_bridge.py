"""Workflow directives and web fetch helpers."""

import pytest
from collaboration_chat_bridge.web_fetch import WebFetchError, fetch_public_text
from collaboration_chat_bridge.workflow_bridge import (
    resolve_workflow_from_messages,
    strip_workflow_directives_from_text,
)


def test_strip_workflow_and_wfp():
    raw = """!wf sop_case_summary_v1
!wfp audience=executive report_label=Q4
Please summarize."""
    cleaned, wid, params = strip_workflow_directives_from_text(raw)
    assert wid == "sop_case_summary_v1"
    assert params.get("audience") == "executive"
    assert params.get("report_label") == "Q4"
    assert "summarize" in cleaned


def test_strip_style_executive():
    raw = "!style executive\nWhat are risks?"
    cleaned, wid, params = strip_workflow_directives_from_text(raw)
    assert wid is None
    assert params.get("audience") == "executive"
    assert "risks" in cleaned


def test_resolve_workflow_last_user_only():
    msgs, wid, p = resolve_workflow_from_messages(
        [
            {"role": "user", "content": "old"},
            {"role": "user", "content": "!wf sop_case_summary_v1\nGo."},
        ],
    )
    assert wid == "sop_case_summary_v1"
    assert msgs[-1]["content"] == "Go."


def test_web_fetch_blocks_private_ip():
    with pytest.raises(WebFetchError):
        fetch_public_text("http://192.168.1.1/x")
