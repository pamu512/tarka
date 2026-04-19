"""Strict validation for Decision API evaluate JSON (TypedDict contract)."""

from __future__ import annotations

from typing import Any, cast

from fraud_stack_sdk.client import EvaluateResponse, InferenceContext


class EvaluateResponseValidationError(ValueError):
    """Raised when the API response does not match the expected evaluate contract."""


def _require_str(d: dict[str, Any], key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v:
        raise EvaluateResponseValidationError(f"missing or invalid string field: {key!r}")
    return v


def _require_float(d: dict[str, Any], key: str) -> float:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EvaluateResponseValidationError(f"missing or invalid numeric field: {key!r}")
    return float(v)


def _require_list_str(d: dict[str, Any], key: str) -> list[str]:
    v = d.get(key)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise EvaluateResponseValidationError(f"missing or invalid list[str] field: {key!r}")
    return list(v)


def _parse_inference_context(raw: dict[str, Any]) -> InferenceContext:
    required_num = (
        "integrity_confidence",
        "tamper_risk",
        "network_trust",
        "replay_risk",
        "geo_consistency_risk",
        "colocation_risk",
        "copresence_risk",
        "impossible_travel_risk",
    )
    required_int = ("velocity_events_5m", "velocity_events_1h", "velocity_events_24h")
    for k in required_num:
        _require_float(raw, k)
    for k in required_int:
        v = raw.get(k)
        if not isinstance(v, int) or isinstance(v, bool):
            raise EvaluateResponseValidationError(f"missing or invalid int field: {k!r}")
    _require_str(raw, "schema_version")
    _require_str(raw, "calibration_profile")
    v = raw.get("expected_calibration_version")
    if not isinstance(v, int) or isinstance(v, bool):
        raise EvaluateResponseValidationError("missing or invalid expected_calibration_version")
    _require_str(raw, "confidence_tier")
    _require_list_str(raw, "driver_reasons")
    _require_list_str(raw, "top_signals")
    return cast(InferenceContext, raw)


def parse_evaluate_response(data: dict[str, Any]) -> EvaluateResponse:
    """Validate and return a typed evaluate response; raises EvaluateResponseValidationError on mismatch."""
    if not isinstance(data, dict):
        raise EvaluateResponseValidationError("response must be a JSON object")
    _require_str(data, "trace_id")
    decision = _require_str(data, "decision")
    if decision not in ("allow", "review", "deny"):
        raise EvaluateResponseValidationError(f"invalid decision: {decision!r}")
    score = _require_float(data, "score")
    if score < 0 or score > 100:
        raise EvaluateResponseValidationError("score out of range 0..100")
    tags = _require_list_str(data, "tags")
    inf_raw = data.get("inference_context")
    if not isinstance(inf_raw, dict):
        raise EvaluateResponseValidationError("missing inference_context object")
    inference_context = _parse_inference_context(inf_raw)

    out: EvaluateResponse = {
        "trace_id": data["trace_id"],
        "decision": decision,
        "score": score,
        "tags": tags,
        "inference_context": inference_context,
    }
    if "rule_hits" in data:
        rh = data["rule_hits"]
        if rh is not None and (not isinstance(rh, list) or not all(isinstance(x, str) for x in rh)):
            raise EvaluateResponseValidationError("rule_hits must be list[str] or absent")
        out["rule_hits"] = list(rh) if rh is not None else []
    if "reasons" in data:
        rs = data["reasons"]
        if rs is not None and (not isinstance(rs, list) or not all(isinstance(x, str) for x in rs)):
            raise EvaluateResponseValidationError("reasons must be list[str] or absent")
        out["reasons"] = list(rs) if rs is not None else []
    if "ml_score" in data and data["ml_score"] is not None:
        out["ml_score"] = _require_float(data, "ml_score")
    if data.get("recommended_action") is not None:
        out["recommended_action"] = _require_str(data, "recommended_action")
    if data.get("challenge_policy_id") is not None:
        out["challenge_policy_id"] = _require_str(data, "challenge_policy_id")
    if data.get("challenge_metadata") is not None:
        cm = data["challenge_metadata"]
        if not isinstance(cm, dict):
            raise EvaluateResponseValidationError("challenge_metadata must be object or absent")
        out["challenge_metadata"] = cm
    return out
