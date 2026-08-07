"""Bridge B2/C1: disposition reason enum + maker-checker."""

from __future__ import annotations

import pytest

from case_api.disposition import (
    apply_status_with_maker_checker,
    escalate_status_for_reason,
    normalize_reason_code,
    parse_maker_checker_statuses,
    y_label_class_for_reason,
)


def test_reason_code_enum():
    assert normalize_reason_code("confirmed_fraud") == "CONFIRMED_FRAUD"
    assert y_label_class_for_reason("FALSE_POSITIVE") == "LEGITIMATE"
    with pytest.raises(ValueError):
        normalize_reason_code("NOT_A_CODE")


def test_escalate_fraud_reason():
    assert escalate_status_for_reason("resolved", "CONFIRMED_FRAUD") == "resolved_fraud"
    assert escalate_status_for_reason("closed", "SAR_FILED") == "sar_filed"
    assert escalate_status_for_reason("resolved", "FALSE_POSITIVE") == "resolved_legit"


def test_maker_checker_parks_then_second_actor_approves():
    mc = parse_maker_checker_statuses("")
    parked = apply_status_with_maker_checker(
        current_status="investigating",
        current_labels=[],
        actor="analyst-a",
        requested_status="resolved",
        reason_code="CONFIRMED_FRAUD",
        approve=False,
        maker_statuses=mc,
    )
    assert parked.pending is True
    assert parked.status_applied is False
    assert parked.status == "investigating"
    assert parked.target_status == "resolved_fraud"
    assert any(x.startswith("mc_pending:") for x in parked.labels)

    with pytest.raises(ValueError, match="distinct second actor"):
        apply_status_with_maker_checker(
            current_status=parked.status,
            current_labels=parked.labels,
            actor="analyst-a",
            requested_status=None,
            reason_code=None,
            approve=True,
            maker_statuses=mc,
        )

    approved = apply_status_with_maker_checker(
        current_status=parked.status,
        current_labels=parked.labels,
        actor="analyst-b",
        requested_status=None,
        reason_code=None,
        approve=True,
        maker_statuses=mc,
    )
    assert approved.status_applied is True
    assert approved.status == "resolved_fraud"
    assert approved.pending is False
    assert not any(x.startswith("mc_pending:") for x in approved.labels)


def test_low_impact_applies_immediately():
    mc = parse_maker_checker_statuses("")
    out = apply_status_with_maker_checker(
        current_status="open",
        current_labels=[],
        actor="analyst-a",
        requested_status="resolved",
        reason_code="FALSE_POSITIVE",
        approve=False,
        maker_statuses=mc,
    )
    assert out.status_applied is True
    assert out.status == "resolved_legit"
    assert "disposition:FALSE_POSITIVE" in out.labels
