"""Live evaluation wire contract: client payloads are ``RiskDecision`` only."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from orchestrator.schemas.domain_boundaries import (
    RiskDecision,
    is_unauthorized_business_metric_key,
    risk_decision_from_rule_engine_payload,
)

logger = logging.getLogger(__name__)

_ARCHITECTURAL_BOUNDARY_EVENT = "orchestrator_architectural_boundary_violation"


def _strip_unauthorized_business_metric_keys(
    value: Any,
    *,
    path: str = "",
) -> tuple[Any, list[str]]:
    """Return a deep copy with forbidden business-metric keys removed."""
    removed: list[str] = []

    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, nested in value.items():
            key_s = str(key)
            key_path = f"{path}.{key_s}" if path else key_s
            if is_unauthorized_business_metric_key(key_s):
                removed.append(key_path)
                continue
            cleaned_nested, nested_removed = _strip_unauthorized_business_metric_keys(
                nested,
                path=key_path,
            )
            removed.extend(nested_removed)
            cleaned[key_s] = cleaned_nested
        return cleaned, removed

    if isinstance(value, list):
        cleaned_list: list[Any] = []
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            cleaned_item, item_removed = _strip_unauthorized_business_metric_keys(
                item,
                path=item_path,
            )
            removed.extend(item_removed)
            cleaned_list.append(cleaned_item)
        return cleaned_list, removed

    return value, removed


def _log_architectural_boundary_violation(*, removed_paths: list[str], stage: str) -> None:
    logger.critical(
        "%s stage=%s removed_key_paths=%s",
        _ARCHITECTURAL_BOUNDARY_EVENT,
        stage,
        removed_paths,
        extra={
            "event": _ARCHITECTURAL_BOUNDARY_EVENT,
            "stage": stage,
            "removed_key_paths": removed_paths,
        },
    )


def finalize_live_evaluation_wire_payload(raw_rule_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Post-execution gate before returning evaluation output to API clients.

    Strips unauthorized business P&L keys, validates against ``RiskDecision``, and re-scans
    the serialized payload so nothing monetary leaks on the wire.
    """
    if not isinstance(raw_rule_payload, dict):
        raw_rule_payload = {}

    pre_cleaned, pre_removed = _strip_unauthorized_business_metric_keys(raw_rule_payload)
    if pre_removed:
        _log_architectural_boundary_violation(removed_paths=pre_removed, stage="pre_validation")

    try:
        decision = risk_decision_from_rule_engine_payload(
            pre_cleaned if isinstance(pre_cleaned, dict) else {},
        )
    except (ValidationError, ValueError, TypeError) as exc:
        logger.critical(
            "%s stage=validation_failed error=%s",
            _ARCHITECTURAL_BOUNDARY_EVENT,
            exc,
        )
        raise ValueError("live evaluation payload failed RiskDecision validation") from exc

    wire_payload = decision.model_dump(mode="json")
    post_cleaned, post_removed = _strip_unauthorized_business_metric_keys(wire_payload)
    if post_removed:
        _log_architectural_boundary_violation(removed_paths=post_removed, stage="post_validation")

    if not isinstance(post_cleaned, dict):
        post_cleaned = {}

    try:
        final_decision = RiskDecision.model_validate(post_cleaned)
    except ValidationError as exc:
        logger.critical(
            "%s stage=post_validation_failed error=%s",
            _ARCHITECTURAL_BOUNDARY_EVENT,
            exc,
        )
        raise ValueError("live evaluation wire payload failed post-validation") from exc

    return final_decision.model_dump(mode="json")
