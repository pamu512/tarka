"""P2: backtest-before-promote gate."""

from __future__ import annotations

from decision_api.backtest_promote_gate import (
    backtest_before_promote_gate,
    metrics_from_backtest,
)


def test_metrics_from_backtest():
    m = metrics_from_backtest(
        {
            "rows_processed": 200,
            "precision": 0.8,
            "recall": 0.7,
            "false_positive_rate": 0.05,
        }
    )
    assert m["events_evaluated"] == 200
    assert m["precision"] == 0.8


def test_waived_without_job():
    gate = backtest_before_promote_gate(
        job_status=None,
        metrics_json=None,
        kill_criteria={"min_precision": 0.5, "min_recall": 0.5, "min_events": 100},
        require_job=False,
        job_id=None,
    )
    assert gate["waived"] is True
    assert gate["promote_allowed"] is True


def test_require_job_blocks_missing():
    gate = backtest_before_promote_gate(
        job_status=None,
        metrics_json=None,
        kill_criteria={},
        require_job=True,
        job_id=None,
    )
    assert gate["promote_allowed"] is False
    assert "backtest_job_id_required" in gate["blockers"]


def test_pending_job_blocks():
    gate = backtest_before_promote_gate(
        job_status="pending",
        metrics_json={"precision": 0.9, "recall": 0.9, "rows_processed": 500},
        kill_criteria={"min_precision": 0.01, "min_recall": 0.01, "min_events": 10},
        require_job=True,
        job_id="11111111-1111-1111-1111-111111111111",
    )
    assert gate["promote_allowed"] is False
    assert any("not_succeeded" in b for b in gate["blockers"])


def test_succeeded_job_passes_kill():
    gate = backtest_before_promote_gate(
        job_status="succeeded",
        metrics_json={
            "precision": 0.9,
            "recall": 0.9,
            "false_positive_rate": 0.01,
            "rows_processed": 500,
        },
        kill_criteria={
            "min_precision": 0.01,
            "min_recall": 0.01,
            "max_false_positive_rate": 0.95,
            "min_events": 100,
        },
        require_job=True,
        job_id="11111111-1111-1111-1111-111111111111",
    )
    assert gate["promote_allowed"] is True
    assert gate["waived"] is False


def test_succeeded_job_fails_kill():
    gate = backtest_before_promote_gate(
        job_status="succeeded",
        metrics_json={
            "precision": 0.01,
            "recall": 0.01,
            "false_positive_rate": 0.9,
            "rows_processed": 500,
        },
        kill_criteria={
            "min_precision": 0.5,
            "min_recall": 0.5,
            "max_false_positive_rate": 0.1,
            "min_events": 100,
        },
        require_job=True,
        job_id="11111111-1111-1111-1111-111111111111",
    )
    assert gate["promote_allowed"] is False
    assert gate["blockers"]
