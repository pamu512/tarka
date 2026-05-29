"""AI-powered rule recommendation engine.

Analyzes historical decisions to surface patterns and propose new rules.
Uses statistical analysis (no external ML dependencies needed):
1. Feature importance via information gain / chi-squared proxy
2. Threshold discovery via percentile analysis
3. Pattern mining for multi-condition rules
"""

import logging
import math
from collections import Counter, defaultdict
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class RuleRecommendation(BaseModel):
    """A recommended rule with confidence metrics."""

    rule_id: str
    description: str
    conditions: list[dict[str, Any]]
    suggested_score_delta: float
    suggested_tags: list[str] = Field(default_factory=list)
    confidence: float  # 0-1, how confident we are in this rule
    support: int  # number of historical events that match
    precision: float  # proportion of matches that were actually fraud
    recall: float  # proportion of fraud captured by this rule
    lift: float  # how much better than random


class FeatureInsight(BaseModel):
    """Insight about a single feature's fraud correlation."""

    feature: str
    importance: float  # 0-1 importance score
    fraud_mean: float
    legit_mean: float
    fraud_std: float
    legit_std: float
    suggested_threshold: float | None = None
    suggested_op: str = "gte"
    description: str = ""


def _entropy(counts: dict[str, int]) -> float:
    """Shannon entropy."""
    total = sum(counts.values())
    if total == 0:
        return 0
    ent = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            ent -= p * math.log2(p)
    return ent


def _information_gain(
    feature_vals: list[float],
    labels: list[str],
    threshold: float,
) -> float:
    """Information gain of splitting on feature >= threshold."""
    total = len(labels)
    if total == 0:
        return 0

    parent_counts: dict[str, int] = Counter(labels)
    parent_ent = _entropy(parent_counts)

    above_labels = [lbl for v, lbl in zip(feature_vals, labels) if v >= threshold]
    below_labels = [lbl for v, lbl in zip(feature_vals, labels) if v < threshold]

    above_ent = _entropy(Counter(above_labels))
    below_ent = _entropy(Counter(below_labels))

    n_above = len(above_labels)
    n_below = len(below_labels)

    child_ent = (n_above / total) * above_ent + (n_below / total) * below_ent
    return parent_ent - child_ent


def analyze_features(
    records: list[dict[str, Any]],
) -> list[FeatureInsight]:
    """Analyze feature distributions across fraud/legit decisions."""
    fraud_features: dict[str, list[float]] = defaultdict(list)
    legit_features: dict[str, list[float]] = defaultdict(list)

    for rec in records:
        decision = rec.get("decision", "allow")
        is_fraud = decision in ("deny", "review")
        snapshot = rec.get("payload_snapshot") or {}
        features = {**snapshot.get("payload", {}), **snapshot.get("metadata", {})}

        for key, val in features.items():
            try:
                fval = (
                    float(val) if not isinstance(val, bool) else (1.0 if val else 0.0)
                )
            except (TypeError, ValueError):
                continue
            if is_fraud:
                fraud_features[key].append(fval)
            else:
                legit_features[key].append(fval)

    insights = []
    all_features = set(fraud_features.keys()) | set(legit_features.keys())

    for feat in all_features:
        f_vals = fraud_features.get(feat, [])
        l_vals = legit_features.get(feat, [])

        if len(f_vals) < 5 or len(l_vals) < 5:
            continue

        f_mean = sum(f_vals) / len(f_vals)
        l_mean = sum(l_vals) / len(l_vals)
        f_std = (
            math.sqrt(sum((v - f_mean) ** 2 for v in f_vals) / len(f_vals))
            if len(f_vals) > 1
            else 0
        )
        l_std = (
            math.sqrt(sum((v - l_mean) ** 2 for v in l_vals) / len(l_vals))
            if len(l_vals) > 1
            else 0
        )

        pooled_std = math.sqrt((f_std**2 + l_std**2) / 2) if (f_std + l_std) > 0 else 1
        effect_size = abs(f_mean - l_mean) / max(pooled_std, 1e-8)
        importance = min(1.0, effect_size / 3.0)

        all_vals = f_vals + l_vals
        labels = ["fraud"] * len(f_vals) + ["legit"] * len(l_vals)

        best_ig = 0
        best_threshold = None

        percentiles = [10, 25, 50, 75, 90]
        thresholds = list(
            set(
                sorted(all_vals)[int(len(all_vals) * p / 100)]
                for p in percentiles
                if int(len(all_vals) * p / 100) < len(all_vals)
            )
        )

        for t in thresholds:
            ig = _information_gain(all_vals, labels, t)
            if ig > best_ig:
                best_ig = ig
                best_threshold = t

        op = "gte" if f_mean > l_mean else "lte"

        desc = (
            f"{'Higher' if f_mean > l_mean else 'Lower'} {feat} correlates with fraud"
        )
        if best_threshold is not None:
            desc += f" (threshold: {best_threshold:.2f})"

        insights.append(
            FeatureInsight(
                feature=feat,
                importance=round(importance, 4),
                fraud_mean=round(f_mean, 4),
                legit_mean=round(l_mean, 4),
                fraud_std=round(f_std, 4),
                legit_std=round(l_std, 4),
                suggested_threshold=round(best_threshold, 4)
                if best_threshold is not None
                else None,
                suggested_op=op,
                description=desc,
            )
        )

    insights.sort(key=lambda x: x.importance, reverse=True)
    return insights


def generate_recommendations(
    records: list[dict[str, Any]],
    max_rules: int = 10,
    min_confidence: float = 0.3,
    min_support: int = 5,
) -> list[RuleRecommendation]:
    """Generate rule recommendations from historical data."""
    insights = analyze_features(records)
    if not insights:
        return []

    total = len(records)
    fraud_count = sum(1 for r in records if r.get("decision") in ("deny", "review"))
    base_fraud_rate = fraud_count / max(total, 1)

    recommendations: list[RuleRecommendation] = []

    for i, insight in enumerate(insights[:15]):
        if insight.suggested_threshold is None:
            continue

        matches = 0
        fraud_matches = 0

        for rec in records:
            snapshot = rec.get("payload_snapshot") or {}
            features = {**snapshot.get("payload", {}), **snapshot.get("metadata", {})}
            val = features.get(insight.feature)
            if val is None:
                continue
            try:
                fval = (
                    float(val) if not isinstance(val, bool) else (1.0 if val else 0.0)
                )
            except (TypeError, ValueError):
                continue

            if insight.suggested_op == "gte" and fval >= insight.suggested_threshold:
                matches += 1
                if rec.get("decision") in ("deny", "review"):
                    fraud_matches += 1
            elif insight.suggested_op == "lte" and fval <= insight.suggested_threshold:
                matches += 1
                if rec.get("decision") in ("deny", "review"):
                    fraud_matches += 1

        if matches < min_support:
            continue

        precision = fraud_matches / max(matches, 1)
        recall = fraud_matches / max(fraud_count, 1)
        lift = precision / max(base_fraud_rate, 1e-8)
        confidence = min(
            1.0, (precision * 0.5 + min(1.0, lift / 5) * 0.3 + insight.importance * 0.2)
        )

        if confidence < min_confidence:
            continue

        score_delta = round(max(5, min(40, precision * 50)), 0)

        tag = f"ai:{insight.feature}_anomaly"

        recommendations.append(
            RuleRecommendation(
                rule_id=f"ai_rec_{i + 1}_{insight.feature}",
                description=f"Auto-detected: {insight.description}",
                conditions=[
                    {
                        "field": insight.feature,
                        "op": insight.suggested_op,
                        "value": insight.suggested_threshold,
                    }
                ],
                suggested_score_delta=score_delta,
                suggested_tags=[tag],
                confidence=round(confidence, 4),
                support=matches,
                precision=round(precision, 4),
                recall=round(recall, 4),
                lift=round(lift, 4),
            )
        )

    # Multi-condition rules from top-2 feature combinations
    top_features = insights[:5]
    for i in range(len(top_features)):
        for j in range(i + 1, len(top_features)):
            f1, f2 = top_features[i], top_features[j]
            if f1.suggested_threshold is None or f2.suggested_threshold is None:
                continue

            matches = 0
            fraud_matches = 0

            for rec in records:
                snapshot = rec.get("payload_snapshot") or {}
                features = {
                    **snapshot.get("payload", {}),
                    **snapshot.get("metadata", {}),
                }

                v1 = features.get(f1.feature)
                v2 = features.get(f2.feature)
                if v1 is None or v2 is None:
                    continue

                try:
                    fv1 = (
                        float(v1) if not isinstance(v1, bool) else (1.0 if v1 else 0.0)
                    )
                    fv2 = (
                        float(v2) if not isinstance(v2, bool) else (1.0 if v2 else 0.0)
                    )
                except (TypeError, ValueError):
                    continue

                match1 = (
                    fv1 >= f1.suggested_threshold
                    if f1.suggested_op == "gte"
                    else fv1 <= f1.suggested_threshold
                )
                match2 = (
                    fv2 >= f2.suggested_threshold
                    if f2.suggested_op == "gte"
                    else fv2 <= f2.suggested_threshold
                )

                if match1 and match2:
                    matches += 1
                    if rec.get("decision") in ("deny", "review"):
                        fraud_matches += 1

            if matches < min_support:
                continue

            precision = fraud_matches / max(matches, 1)
            recall = fraud_matches / max(fraud_count, 1)
            lift = precision / max(base_fraud_rate, 1e-8)
            confidence = min(
                1.0,
                (
                    precision * 0.5
                    + min(1.0, lift / 5) * 0.3
                    + (f1.importance + f2.importance) / 2 * 0.2
                ),
            )

            if confidence < min_confidence:
                continue

            score_delta = round(max(10, min(50, precision * 60)), 0)

            recommendations.append(
                RuleRecommendation(
                    rule_id=f"ai_rec_combo_{f1.feature}_{f2.feature}",
                    description=f"Auto-detected combination: {f1.feature} + {f2.feature}",
                    conditions=[
                        {
                            "field": f1.feature,
                            "op": f1.suggested_op,
                            "value": f1.suggested_threshold,
                        },
                        {
                            "field": f2.feature,
                            "op": f2.suggested_op,
                            "value": f2.suggested_threshold,
                        },
                    ],
                    suggested_score_delta=score_delta,
                    suggested_tags=[f"ai:{f1.feature}+{f2.feature}"],
                    confidence=round(confidence, 4),
                    support=matches,
                    precision=round(precision, 4),
                    recall=round(recall, 4),
                    lift=round(lift, 4),
                )
            )

    recommendations.sort(key=lambda x: x.confidence, reverse=True)
    return recommendations[:max_rules]


class RuleRecommender:
    """Legacy compatibility wrapper.

    The original class-based API is preserved so that existing callers
    (recommendation_api.py) continue to work without changes.
    """

    def __init__(self) -> None:
        self._observations: list[dict[str, Any]] = []

    def ingest(self, records: list[dict[str, Any]]) -> None:
        self._observations.extend(records)

    def analyze(
        self, min_support: int = 10, min_precision: float = 0.6
    ) -> list[dict[str, Any]]:
        if len(self._observations) < 20:
            return [
                {
                    "error": "insufficient_data",
                    "required": 20,
                    "have": len(self._observations),
                }
            ]

        positive = [
            o for o in self._observations if o.get("decision") in ("deny", "review")
        ]
        negative = [o for o in self._observations if o.get("decision") == "allow"]

        if not positive or not negative:
            return [{"error": "need_both_positive_and_negative_cases"}]

        records = [
            {
                "decision": o["decision"],
                "score": o.get("score", 0),
                "payload_snapshot": {"payload": o.get("features", {}), "metadata": {}},
            }
            for o in self._observations
        ]

        analyze_features(records)
        recs = generate_recommendations(
            records, max_rules=20, min_confidence=0.2, min_support=min_support
        )

        results: list[dict[str, Any]] = []
        for rec in recs:
            precision = rec.precision
            if precision < min_precision:
                continue
            coverage = rec.recall
            results.append(
                {
                    "type": "ai_recommendation",
                    "rule": {
                        "id": rec.rule_id,
                        "when": rec.conditions,
                        "score_delta": rec.suggested_score_delta,
                        "tags": rec.suggested_tags,
                        "description": rec.description,
                    },
                    "precision": round(precision, 3),
                    "coverage": round(coverage, 3),
                    "support": rec.support,
                    "quality_score": round(
                        precision * coverage * math.log(max(rec.support, 2)), 3
                    ),
                }
            )

        results.sort(key=lambda r: r["quality_score"], reverse=True)
        return results[:20]
