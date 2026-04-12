import pytest
from investigation_agent import feedback_store


@pytest.fixture(autouse=True)
def isolated_feedback_db(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    feedback_store.reset_connection_for_tests()
    yield
    feedback_store.reset_connection_for_tests()


def test_turn_and_feedback_roundtrip():
    feedback_store.record_turn(
        turn_id="turn-1",
        tenant_id="demo",
        analyst_id="analyst-1",
        case_id="c1",
        playbook_id=None,
        prompt_version="3.2.0",
        reply_preview="hello",
        tool_count=2,
    )
    meta = feedback_store.lookup_turn("turn-1")
    assert meta["tenant_id"] == "demo"
    assert meta.get("persona") is None
    fid = feedback_store.save_feedback(
        turn_id="turn-1",
        tenant_id="demo",
        analyst_id="analyst-1",
        rating=1,
        note="good",
        claim_indices=[0],
    )
    assert fid > 0
    s = feedback_store.feedback_summary("demo", days=7)
    assert s["total"] >= 1
    recent = feedback_store.list_recent_feedback("demo", 10)
    assert any(r["turn_id"] == "turn-1" for r in recent)
