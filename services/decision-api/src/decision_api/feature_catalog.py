"""FeatureCatalog v1 — required/optional evaluate features and producers.

Evaluate-time checks add degrade tags for missing required keys. High-risk
event types can fail closed (force deny) via settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Producer = Literal[
    "payload",
    "device_context",
    "feature_service",
    "counters",
    "graph",
    "evaluate_merge",
]


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    value_type: Literal["str", "number", "bool", "object", "any"]
    producers: tuple[Producer, ...]
    required_for: frozenset[str]
    optional: bool = False


# ponytail: catalog is a static table; bump version string when fields/semantics change.
FEATURE_CATALOG_VERSION = "1"

FEATURE_CATALOG_V1: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="device_fingerprint",
        value_type="str",
        producers=("device_context", "payload", "evaluate_merge"),
        required_for=frozenset({"payment", "login"}),
    ),
    FeatureSpec(
        name="amount",
        value_type="number",
        producers=("payload", "feature_service"),
        required_for=frozenset({"payment"}),
    ),
    FeatureSpec(
        name="session_id",
        value_type="str",
        producers=("payload", "evaluate_merge"),
        required_for=frozenset(),
        optional=True,
    ),
)


def _present(features: dict[str, Any], name: str, value_type: str) -> bool:
    if name not in features:
        return False
    val = features[name]
    if val is None:
        return False
    if value_type == "str":
        return isinstance(val, str) and bool(val.strip())
    if value_type == "number":
        if isinstance(val, bool):
            return False
        if isinstance(val, (int, float)):
            return True
        if isinstance(val, str):
            try:
                float(val)
                return True
            except ValueError:
                return False
        return False
    if value_type == "bool":
        return isinstance(val, bool)
    if value_type == "object":
        return isinstance(val, dict)
    return True


def apply_feature_catalog_v1(
    features: dict[str, Any],
    event_type: str,
    degrade_tags: list[str],
    *,
    fail_closed_event_types: frozenset[str] | set[str] | None = None,
) -> list[str]:
    """Append ``feature:missing_<name>`` tags; return missing required names.

    When ``event_type`` is in ``fail_closed_event_types`` and any required field
    is missing, also append ``feature:catalog_fail_closed``.
    """
    et = (event_type or "").strip().lower()
    missing: list[str] = []
    for spec in FEATURE_CATALOG_V1:
        if et not in spec.required_for:
            continue
        if _present(features, spec.name, spec.value_type):
            continue
        missing.append(spec.name)
        tag = f"feature:missing_{spec.name}"
        if tag not in degrade_tags:
            degrade_tags.append(tag)

    fail_set = fail_closed_event_types or frozenset()
    if missing and et in fail_set:
        if "feature:catalog_fail_closed" not in degrade_tags:
            degrade_tags.append("feature:catalog_fail_closed")
    return missing
