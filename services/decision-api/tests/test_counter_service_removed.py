"""Guard (#2/#3): counter-service is gone; decision-api owns aggregate counters locally.

counter-service duplicated decision-api's replay/parity ops surface and
feature-service's read surface with zero unique endpoints. After the prune:
  - settings has no counter_service_url (no remote counter hop)
  - evaluate/pipeline.py no longer fetches a counter snapshot over HTTP
  - main.py has no counter circuit breaker or fetch helpers

If this test fails, someone reintroduced a counter-service hop.
"""

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "decision_api"


def test_settings_has_no_counter_service_url() -> None:
    from decision_api.config import settings

    assert not hasattr(settings, "counter_service_url"), (
        "counter_service_url must not exist: counters are owned by the local "
        "AggregateStore (services/shared/fraud_aggregates.py)"
    )


def test_pipeline_has_no_remote_counter_fetch() -> None:
    text = (SRC / "evaluate" / "pipeline.py").read_text()
    assert "_fetch_counter_snapshot" not in text
    assert "counter_service" not in text


def test_main_has_no_counter_circuit_or_fetch() -> None:
    text = (SRC / "main.py").read_text()
    assert "_fetch_counter_snapshot" not in text
    assert "_circuit_counter" not in text
    assert "record-and-query" not in text
