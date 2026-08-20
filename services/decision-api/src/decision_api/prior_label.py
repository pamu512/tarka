"""Online prior-fraud label boost.

Reads the y_label store (populated by case disposition / dispute outcomes)
and returns a bounded score delta + audit tag when the entity has a confirmed
fraud label.  This is the "model learned" consumer — first-party ground truth
feeding back into the next evaluate for the same entity.

The delta is additive (progressive friction, not a hard wall).  Unknown /
empty / legitimate labels produce zero delta.
"""

from __future__ import annotations

from decision_api import config as _config
from decision_api.y_label_store import load_y_labels

_TAG = "label:prior_fraud"
_RULE_HIT = "prior_fraud_label"


def lookup_prior_fraud_delta(
    tenant_id: str,
    entity_id: str,
) -> tuple[float, list[str], list[str]]:
    """Return ``(delta, tags, rule_hits)`` for a prior FRAUD y_label.

    * FRAUD ("1") → ``(prior_label_max_delta, [tag], [hit])``
    * Anything else (missing, "0", no store) → ``(0.0, [], [])``

    Bounded by ``settings.prior_label_max_delta`` (default 10).
    """
    settings = _config.settings
    if not settings.prior_label_score_enabled:
        return 0.0, [], []

    labels = load_y_labels(tenant_id)
    entity_label = labels.get("by_entity", {}).get(entity_id)

    if entity_label != "1":
        return 0.0, [], []

    delta = max(0.0, min(100.0, float(settings.prior_label_max_delta)))
    return delta, [_TAG], [_RULE_HIT]
