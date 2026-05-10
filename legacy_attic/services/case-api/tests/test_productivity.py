from types import SimpleNamespace

from case_api.main import _apply_case_mutations


def test_apply_case_mutations_updates_core_fields():
    case = SimpleNamespace(status="open", priority="medium", assigned_team=None, labels=["a"])
    _apply_case_mutations(
        case,
        {
            "status": "investigating",
            "priority": "high",
            "assigned_team": "fraud-l2",
            "labels": ["b", "a"],
        },
    )
    assert case.status == "investigating"
    assert case.priority == "high"
    assert case.assigned_team == "fraud-l2"
    assert case.labels == ["a", "b"]
