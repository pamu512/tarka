"""Map entity velocity aggregates + EWMA baselines → trend window_rows (never invent)."""

from __future__ import annotations

from typing import Any

from analytics import trend_store

# Observed feature key → (metric_key, window)
_FEATURE_MAP: tuple[tuple[str, str, str], ...] = (
    ("event_count_5m", "sub_1min_velocity", "sub_1min"),
    ("event_count_24h", "sub_24h_velocity", "sub_24h"),
    ("failed_auth_5m", "failed_auth_velocity", "sub_1min"),
    ("failed_auth_24h", "failed_auth_velocity", "sub_24h"),
)


def extract_observed_metrics(features: dict[str, Any] | None) -> dict[str, float]:
    """Pull mapped observed counts from aggregate_features-style dict."""
    feats = features if isinstance(features, dict) else {}
    out: dict[str, float] = {}
    for feat_key, metric_key, _win in _FEATURE_MAP:
        if feat_key not in feats:
            continue
        try:
            out[f"{metric_key}|{_win}"] = float(feats[feat_key])
        except (TypeError, ValueError):
            continue
    return out


def build_window_rows_or_none(
    *,
    tenant_id: str,
    entity_id: str,
    features: dict[str, Any] | None,
    record: bool = True,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """
    Update EWMA from current observations; return window_rows only when every
    observed metric has a prior ready baseline (n >= TREND_BASELINE_MIN_N from
    previous ticks). Never invents means from a single sample.
    """
    observed = extract_observed_metrics(features)
    meta: dict[str, Any] = {"observed_keys": list(observed.keys()), "baselines": []}
    if not observed:
        return None, {**meta, "skip_reason": "no_mapped_velocity_features"}

    rows: list[dict[str, Any]] = []
    all_ready = True
    for composite, obs in observed.items():
        metric_key, window = composite.split("|", 1)
        # Store baselines per metric+window to avoid 5m/24h collisions.
        store_key = composite
        prior = trend_store.baseline_snapshot(
            tenant_id=tenant_id, entity_id=entity_id, metric_key=store_key
        )
        prior_ready = bool(prior and prior.get("ready"))
        prior_mean = float(prior["ewma_mean"]) if prior else None
        prior_std = float(prior["ewma_std"]) if prior else 0.0

        if record:
            snap = trend_store.record_observation(
                tenant_id=tenant_id,
                entity_id=entity_id,
                metric_key=store_key,
                observed=obs,
            )
        else:
            snap = prior or {
                "metric_key": store_key,
                "n": 0,
                "ewma_mean": 0.0,
                "ewma_std": 0.0,
                "ready": False,
                "min_n": trend_store.baseline_min_n(),
            }
        meta["baselines"].append(snap)

        if not prior_ready or prior_mean is None:
            all_ready = False
            continue
        rows.append(
            {
                "metric_key": metric_key,
                "window": window,
                "observed": obs,
                "baseline_mean": prior_mean,
                "baseline_std": prior_std if prior_std > 1e-9 else 1e-9,
            }
        )

    if not all_ready or not rows:
        return None, {**meta, "skip_reason": "insufficient_baseline"}
    return rows, meta
