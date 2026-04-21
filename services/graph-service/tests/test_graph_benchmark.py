"""DGFraud issues #64–#66: benchmark tasks, feature registry, experiment runner."""

from graph_service.benchmark.datasets import get_task, list_tasks
from graph_service.benchmark.metrics import average_precision_binary, precision_recall
from graph_service.benchmark.registry import export_for_decision_pipeline, feature_ids, registry_content_digest
from graph_service.benchmark.runner import run_experiment


def test_list_tasks_schema():
    d = list_tasks()
    assert d["schema"] == "tarka.graph_benchmark_tasks/v1"
    assert len(d["tasks"]) >= 2
    assert get_task("binary_entity_high_risk") is not None


def test_feature_registry_export_and_digest_stable():
    a = export_for_decision_pipeline()
    b = export_for_decision_pipeline()
    assert a == b
    assert a["schema"] == "tarka.graph_feature_registry/v1"
    assert registry_content_digest() == registry_content_digest()
    expected = {
        "graph.ring_membership_count",
        "graph.shared_attribute_density",
        "graph.community_risk_score",
        "graph.propagated_risk_peak",
    }
    assert feature_ids() == expected


def test_backward_compatible_feature_ids():
    """Adding optional metadata must not rename or remove existing feature_ids."""
    exported = export_for_decision_pipeline()["features"]
    ids = {f["feature_id"] for f in exported}
    assert ids == feature_ids()
    for f in exported:
        assert "version" in f and "owner" in f and "derivation" in f and "decision_pipeline_key" in f


def test_metrics_perfect_ranking():
    y_true = [0, 1, 1, 0]
    scores = [0.1, 0.9, 0.8, 0.2]
    p, r = precision_recall(y_true, scores, threshold=0.5)
    assert p == 1.0 and r == 1.0
    assert average_precision_binary(y_true, scores) == 1.0


def test_experiment_scorecard_deterministic():
    body = {
        "task_id": "binary_entity_high_risk",
        "y_true": [0, 1, 0, 1, 1],
        "baseline_scores": [0.2, 0.45, 0.3, 0.55, 0.6],
        "graph_scores": [0.15, 0.62, 0.28, 0.7, 0.65],
    }
    a = run_experiment(seed=7, **body)
    b = run_experiment(seed=7, **body)
    assert a["run_id"] == b["run_id"]
    assert a["artifact_digest"] == b["artifact_digest"]
    assert a["promotion"]["decision"] in {"promote_graph_enhanced", "hold", "rollback_graph_enhanced"}


def test_benchmark_http_flow(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    from fastapi.testclient import TestClient
    from graph_service.main import app

    with TestClient(app) as client:
        d = client.get("/v1/benchmark/datasets")
        assert d.status_code == 200
        f = client.get("/v1/benchmark/features")
        assert f.status_code == 200
        assert f.json()["content_digest"]
        r = client.post(
            "/v1/benchmark/runs",
            json={
                "seed": 1,
                "task_id": "binary_entity_high_risk",
                "y_true": [0, 1],
                "baseline_scores": [0.4, 0.45],
                "graph_scores": [0.3, 0.8],
            },
        )
        assert r.status_code == 201, r.text
        rid = r.json()["run_id"]
        g = client.get(f"/v1/benchmark/runs/{rid}")
        assert g.status_code == 200
        assert g.json()["artifact_digest"] == r.json()["artifact_digest"]
