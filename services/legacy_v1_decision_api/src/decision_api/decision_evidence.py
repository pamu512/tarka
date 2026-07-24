"""Point-in-time evidence snapshot attached to each durable decision audit."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from decision_api.json_rules import get_json_rule_engine_metadata
from decision_api.rule_content_identity import engine_build_identity


def build_decision_evidence_snapshot(
    *,
    feature_map: dict[str, Any] | None,
    rule_pack_content_sha256: str,
    rule_pack_files: list[str],
    condition_trace: list[dict[str, Any]] | None = None,
    external_signal_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Immutable evidence fields for ``payload_snapshot.decision_evidence``."""
    features = feature_map if isinstance(feature_map, dict) else {}
    return {
        "evaluated_at": datetime.now(UTC).isoformat(),
        "feature_map": features,
        "rule_pack_content_sha256": rule_pack_content_sha256,
        "rule_pack_files": sorted(str(x) for x in rule_pack_files if str(x).strip()),
        "condition_trace": list(condition_trace or []),
        "external_signal_snapshot": external_signal_meta
        if isinstance(external_signal_meta, dict)
        else {},
        "json_rule_engine": get_json_rule_engine_metadata(),
        "engine_build": engine_build_identity(),
    }
