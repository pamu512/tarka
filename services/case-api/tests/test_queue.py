from types import SimpleNamespace

from case_api.main import _queue_score, _recommended_action


def _case(priority: str, status: str, labels: list[str]):
    return SimpleNamespace(priority=priority, status=status, labels=labels)


def test_queue_score_boosts_critical_and_labels():
    c = _case("critical", "open", ["confirmed_fraud"])
    score = _queue_score(c)
    assert score >= 140
    assert _recommended_action(c, score) == "immediate_triage"


def test_queue_score_lower_for_closed_low():
    c = _case("low", "closed", [])
    score = _queue_score(c)
    assert score < 0
    assert _recommended_action(c, score) == "monitor"
