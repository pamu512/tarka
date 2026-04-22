from __future__ import annotations
from typing import Any

"""Built-in investigation playbooks (short ids for `playbook_id` on case create)."""
PLAYBOOKS: dict[str, dict[str, Any]] = {
    "escalate_fraud": {
        "status": "investigating",
        "priority": "critical",
        "labels": ["escalated", "fraud_watch"],
        "assigned_team": "fraud-l2",
        "comment": "Playbook applied: escalate_fraud",
    },
    "expedite_chargeback": {
        "status": "investigating",
        "priority": "high",
        "labels": ["chargeback", "expedited"],
        "assigned_team": "chargeback-ops",
        "comment": "Playbook applied: expedite_chargeback",
    },
    "close_false_positive": {
        "status": "closed",
        "priority": "low",
        "labels": ["false_positive", "closed_clean"],
        "assigned_team": "qa-review",
        "comment": "Playbook applied: close_false_positive",
    },
}
