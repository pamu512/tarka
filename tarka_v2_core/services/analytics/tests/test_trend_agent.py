"""Unit tests for trend agent deterministic gates (no Ollama/DB)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trend_agent import (
    MetricKey,
    ResolutionStatus,
    SuggestedAction,
    TargetScope,
    TargetSignature,
    TrendAgent,
    TrendAgentSettings,
    TrendDecisionEnvelope,
    build_draft_rule_package,
    envelope_action_payload,
    try_resolve_systemic,
)


class _NoOpSynthesizer:
    def close(self) -> None:
        return None


def test_try_resolve_systemic_with_hil_exclusion() -> None:
    rag = {
        "tactical_snapshots": [{"tx_volume_usd": 5000.0, "tx_count": 1, "failed_auth_count": 0}],
        "cascading_baselines": {
            "1d": {"tx_volume_mean": 5000.0, "tx_volume_std": 100.0},
            "90d": {"tx_volume_mean": 100.0, "tx_volume_std": 50.0},
        },
        "seasonal_historical_3y": {"slices": []},
        "active_hil_exclusions": [
            {"override_type": "ALLOW_SEASONAL_SPIKE", "scope_key": "day_of_year:100"}
        ],
        "active_hil_overrides": [],
        "z_score_validations": [{"z_score": 2.0}],
    }
    env = try_resolve_systemic(rag)
    assert env is not None
    assert env.resolution_status == ResolutionStatus.RESOLVED_SYSTEMIC
    assert env.anomaly_detected is False
    assert env.flag_for_hil_review is False


def test_try_resolve_systemic_with_seasonal_match() -> None:
    rag = {
        "tactical_snapshots": [{"tx_volume_usd": 800.0, "tx_count": 1, "failed_auth_count": 0}],
        "cascading_baselines": {
            "1d": {"tx_volume_mean": 800.0, "tx_volume_std": 10.0},
            "90d": {"tx_volume_mean": 100.0, "tx_volume_std": 20.0},
        },
        "seasonal_historical_3y": {
            "slices": [{"calendar_year": 2024, "tx_volume_mean": 750.0, "sample_days": 1}]
        },
        "active_hil_exclusions": [],
        "active_hil_overrides": [],
        "z_score_validations": [],
    }
    env = try_resolve_systemic(rag)
    assert env is not None
    assert env.resolution_status == ResolutionStatus.RESOLVED_SYSTEMIC


def test_apply_escalation_policy_forces_hil_when_z_high() -> None:
    agent = TrendAgent(
        settings=TrendAgentSettings(trend_database_url="postgresql+asyncpg://local/test"),
        synthesizer=_NoOpSynthesizer(),
    )
    rag = {
        "z_score_validations": [{"metric": "tx_volume_usd", "z_score": 5.2}],
        "seasonal_historical_3y": {"slices": []},
        "active_hil_exclusions": [],
        "active_hil_overrides": [],
        "cascading_baselines": {
            "1d": {"tx_volume_mean": 500.0, "tx_volume_std": 10.0},
            "90d": {"tx_volume_mean": 100.0, "tx_volume_std": 10.0},
        },
    }
    env = TrendDecisionEnvelope(
        resolution_status=ResolutionStatus.CLEAR,
        anomaly_detected=False,
        flag_for_hil_review=False,
        forensic_rationale="Model returned clear.",
    )
    out = agent._apply_escalation_policy(env, rag)
    assert out.resolution_status == ResolutionStatus.ESCALATED
    assert out.flag_for_hil_review is True
    assert out.anomaly_detected is True
    assert out.target_signature is not None


def test_envelope_action_payload_matches_orchestration_schema() -> None:
    env = TrendDecisionEnvelope(
        resolution_status=ResolutionStatus.ESCALATED,
        anomaly_detected=True,
        flag_for_hil_review=True,
        suggested_action=SuggestedAction.BLOCK,
        target_signature=TargetSignature(
            metric_key=MetricKey.FAILED_AUTH_VELOCITY,
            threshold_limit=12,
            scope=TargetScope.REGIONAL_SUBNET,
        ),
        forensic_rationale="Failed-auth Z=5.1 with no seasonal slice.",
    )
    payload = envelope_action_payload(env)
    assert payload["anomaly_detected"] is True
    assert payload["flag_for_hil_review"] is True
    assert payload["suggested_action"] == "BLOCK"
    assert payload["target_signature"]["metric_key"] == "failed_auth_velocity"
    assert payload["target_signature"]["threshold_limit"] == 12


def test_build_draft_rule_package_shape() -> None:
    env = TrendDecisionEnvelope(
        resolution_status=ResolutionStatus.ESCALATED,
        anomaly_detected=True,
        flag_for_hil_review=True,
        suggested_action=SuggestedAction.CHALLENGE,
        target_signature=TargetSignature(
            metric_key=MetricKey.SUB_1MIN_VELOCITY,
            threshold_limit=42,
            scope=TargetScope.ENTITY,
        ),
        forensic_rationale="Spike exceeds 90d baseline with no seasonal anchor.",
    )
    pkg = build_draft_rule_package(env, tenant_id="t1", entity_id="e1")
    assert pkg["status"] == "PENDING_VALIDATION"
    assert pkg["wasm_ready"] is True
    assert pkg["rule"]["predicate"]["threshold"] == 42


def test_apply_feedback_override_records_insert() -> None:
    class RecordingSynth(_NoOpSynthesizer):
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def insert_hil_override(self, *args: object, **kwargs: object) -> None:
            self.calls.append((args, kwargs))

    synth = RecordingSynth()
    agent = TrendAgent(
        settings=TrendAgentSettings(trend_database_url="postgresql+asyncpg://local/test"),
        synthesizer=synth,
    )
    record = agent.apply_feedback_override(
        "tenant-a",
        "entity-b",
        "ALLOW_SEASONAL_SPIKE",
        scope_key="day_of_year:200",
        expires_at=datetime(2027, 1, 1, tzinfo=UTC),
        analyst_rationale="Verified holiday pattern",
    )
    assert record["override_type"] == "ALLOW_SEASONAL_SPIKE"
    assert record["scope_key"] == "day_of_year:200"
    assert len(synth.calls) == 1
