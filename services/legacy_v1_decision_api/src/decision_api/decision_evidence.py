"""Point-in-time evidence snapshot attached to each durable decision audit."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
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
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
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


def build_list_decision_evidence_snapshot(
    *,
    payload: dict[str, Any] | None,
    list_type: str,
    action: str,
    list_entry: dict[str, Any],
    condition_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the normal evidence contract for a list-driven early decision."""
    canonical_list_entry = json.loads(
        json.dumps(
            list_entry,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    )
    policy = {
        "kind": "entity_list_early_decision",
        "version": 1,
        "list_type": str(list_type),
        "action": str(action),
        "list_entry": canonical_list_entry,
    }
    canonical = json.dumps(
        policy,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    policy_hash = hashlib.sha256(canonical).hexdigest()
    evidence = build_decision_evidence_snapshot(
        feature_map=payload if isinstance(payload, dict) else {},
        rule_pack_content_sha256=policy_hash,
        rule_pack_files=[f"entity-list-policy:{list_type}"],
        condition_trace=list(condition_trace or [])
        + [
            {
                "step": "entity_list_early_decision",
                "status": "matched",
                "list_type": str(list_type),
                "action": str(action),
            }
        ],
    )
    evidence["list_entry"] = canonical_list_entry
    return evidence
