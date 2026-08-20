"""Prior-fraud label boost: y_label "1" on entity → hotter next evaluate score."""

from __future__ import annotations

import pytest

from decision_api.prior_label import _RULE_HIT, _TAG, lookup_prior_fraud_delta
from decision_api.y_label_store import merge_y_labels


@pytest.fixture(autouse=True)
def _calibration_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))


# --- unit: lookup_prior_fraud_delta ---


def test_fraud_label_produces_delta(monkeypatch):
    """Entity with FRAUD y_label → +10 delta, tag, rule_hit."""
    monkeypatch.setenv("PRIOR_LABEL_SCORE_ENABLED", "true")
    monkeypatch.setenv("PRIOR_LABEL_MAX_DELTA", "10")
    _reload_settings(monkeypatch)

    merge_y_labels("tenant-a", by_entity={"entity-1": "1"})

    delta, tags, hits = lookup_prior_fraud_delta("tenant-a", "entity-1")
    assert delta == 10.0
    assert _TAG in tags
    assert _RULE_HIT in hits


def test_no_label_no_delta(monkeypatch):
    """Entity with no y_label → 0 delta, no tags."""
    monkeypatch.setenv("PRIOR_LABEL_SCORE_ENABLED", "true")
    _reload_settings(monkeypatch)

    delta, tags, hits = lookup_prior_fraud_delta("tenant-a", "entity-clean")
    assert delta == 0.0
    assert tags == []
    assert hits == []


def test_legitimate_label_no_delta(monkeypatch):
    """Entity with LEGITIMATE ("0") y_label → 0 delta."""
    monkeypatch.setenv("PRIOR_LABEL_SCORE_ENABLED", "true")
    _reload_settings(monkeypatch)

    merge_y_labels("tenant-b", by_entity={"entity-legit": "0"})

    delta, tags, hits = lookup_prior_fraud_delta("tenant-b", "entity-legit")
    assert delta == 0.0
    assert tags == []
    assert hits == []


def test_disabled_setting_no_delta(monkeypatch):
    """Feature flag off → always 0 delta even with a fraud label stored."""
    monkeypatch.setenv("PRIOR_LABEL_SCORE_ENABLED", "false")
    _reload_settings(monkeypatch)

    merge_y_labels("tenant-c", by_entity={"entity-fraud": "1"})

    delta, tags, hits = lookup_prior_fraud_delta("tenant-c", "entity-fraud")
    assert delta == 0.0
    assert tags == []
    assert hits == []


def test_max_delta_cap(monkeypatch):
    """Custom cap respected; cannot exceed 100."""
    monkeypatch.setenv("PRIOR_LABEL_SCORE_ENABLED", "true")
    monkeypatch.setenv("PRIOR_LABEL_MAX_DELTA", "25")
    _reload_settings(monkeypatch)

    merge_y_labels("tenant-d", by_entity={"entity-x": "1"})

    delta, _, _ = lookup_prior_fraud_delta("tenant-d", "entity-x")
    assert delta == 25.0


def test_same_payload_fraud_vs_clean_score_difference(monkeypatch):
    """Core acceptance test: identical entity_id, one with FRAUD label scores higher."""
    monkeypatch.setenv("PRIOR_LABEL_SCORE_ENABLED", "true")
    monkeypatch.setenv("PRIOR_LABEL_MAX_DELTA", "10")
    _reload_settings(monkeypatch)

    merge_y_labels("tenant-e", by_entity={"flagged-entity": "1"})

    d_clean, t_clean, h_clean = lookup_prior_fraud_delta("tenant-e", "clean-entity")
    d_fraud, t_fraud, h_fraud = lookup_prior_fraud_delta("tenant-e", "flagged-entity")

    assert d_fraud > d_clean
    assert d_fraud == 10.0
    assert d_clean == 0.0
    assert _TAG in t_fraud
    assert _TAG not in t_clean
    assert _RULE_HIT in h_fraud
    assert _RULE_HIT not in h_clean


def test_missing_store_no_crash(monkeypatch):
    """Non-existent tenant / empty store → graceful 0 delta."""
    monkeypatch.setenv("PRIOR_LABEL_SCORE_ENABLED", "true")
    _reload_settings(monkeypatch)

    delta, tags, hits = lookup_prior_fraud_delta("no-such-tenant", "no-such-entity")
    assert delta == 0.0
    assert tags == []
    assert hits == []


# --- helper ---

def _reload_settings(monkeypatch):
    """Force settings re-read after env var changes."""
    from decision_api import config

    monkeypatch.setattr(config, "settings", config.Settings())
