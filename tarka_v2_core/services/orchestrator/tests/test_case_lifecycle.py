"""Lifecycle case status machine (orchestrator.models.cases)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"  # parent of ``tarka_shared`` package
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orchestrator.models.cases import (
    CaseStatus,
    StateTransitionError,
    transition_status,
)  # noqa: E402


def test_resolved_fraud_to_under_review_without_reason_raises() -> None:
    """Gate: reopening from a terminal disposition requires an audit-grade reopen_reason."""
    with pytest.raises(StateTransitionError, match="reopen_reason"):
        transition_status(CaseStatus.RESOLVED_FRAUD, CaseStatus.UNDER_REVIEW)


def test_resolved_legit_to_under_review_without_reason_raises() -> None:
    with pytest.raises(StateTransitionError, match="reopen_reason"):
        transition_status(CaseStatus.RESOLVED_LEGIT, CaseStatus.UNDER_REVIEW)


def test_resolved_to_under_review_with_reason_succeeds() -> None:
    out = transition_status(
        CaseStatus.RESOLVED_FRAUD,
        CaseStatus.UNDER_REVIEW,
        reopen_reason="Regulator request #4421",
    )
    assert out == CaseStatus.UNDER_REVIEW


def test_resolved_fraud_to_resolved_legit_without_reason_allowed() -> None:
    """Disposition correction between terminal states does not use reopen_reason."""
    out = transition_status(CaseStatus.RESOLVED_FRAUD, CaseStatus.RESOLVED_LEGIT)
    assert out == CaseStatus.RESOLVED_LEGIT


def test_open_to_resolved_auto_allowed() -> None:
    out = transition_status(CaseStatus.OPEN, CaseStatus.RESOLVED_AUTO)
    assert out == CaseStatus.RESOLVED_AUTO


def test_resolved_auto_to_under_review_requires_reason() -> None:
    with pytest.raises(StateTransitionError, match="reopen_reason"):
        transition_status(CaseStatus.RESOLVED_AUTO, CaseStatus.UNDER_REVIEW)


def test_resolved_auto_to_resolved_fraud_without_reason_allowed() -> None:
    out = transition_status(CaseStatus.RESOLVED_AUTO, CaseStatus.RESOLVED_FRAUD)
    assert out == CaseStatus.RESOLVED_FRAUD
