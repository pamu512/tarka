"""Experiment registry holdout flags + list filters (Wave B)."""

from __future__ import annotations

import json

import pytest
from decision_api.config import settings
from decision_api.experiment_api import append_experiment_record, list_experiment_records


@pytest.fixture
def registry_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    return tmp_path / "experiment_registry.jsonl"


def test_append_marks_underpowered_and_kpi(registry_path):
    weak = append_experiment_record(
        "simulation_run",
        events_evaluated=50,
        allow_underpowered=True,
        minimum_recommended_events=200,
    )
    assert weak["underpowered"] is True
    assert weak["holdout_ok"] is True  # override accepted
    assert weak["kpi_eligible"] is False  # still not a KPI

    strong = append_experiment_record(
        "ab_test",
        events_evaluated=500,
        population_id="cohort-a",
        allow_underpowered=False,
        minimum_recommended_events=200,
    )
    assert strong["underpowered"] is False
    assert strong["holdout_ok"] is True
    assert strong["kpi_eligible"] is True

    lines = registry_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["experiment_type"] == "simulation_run"


def test_list_filters_by_type_and_kpi(registry_path):
    append_experiment_record(
        "simulation_run",
        events_evaluated=10,
        allow_underpowered=True,
        population_id="p1",
    )
    append_experiment_record(
        "ab_test",
        events_evaluated=300,
        population_id="p2",
    )
    out = list_experiment_records(limit=50, experiment_type="ab_test")
    assert len(out["experiments"]) == 1
    assert out["experiments"][0]["experiment_type"] == "ab_test"

    kpi_only = list_experiment_records(limit=50, kpi_eligible=True)
    assert len(kpi_only["experiments"]) == 1
    assert kpi_only["experiments"][0]["kpi_eligible"] is True

    by_pop = list_experiment_records(limit=50, population_id="p1")
    assert len(by_pop["experiments"]) == 1
    assert by_pop["experiments"][0]["population_id"] == "p1"
