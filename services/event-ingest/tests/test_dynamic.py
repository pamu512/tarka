"""Heuristic dynamic ingest → contract v1."""

from event_ingest.dynamic import heuristic_map_to_evaluate_request


def test_heuristic_maps_camelcase_aliases() -> None:
    ev = heuristic_map_to_evaluate_request(
        {"tenantId": "acme", "userId": "user-1", "type": "payment", "amount": 12.5},
    )
    assert ev is not None
    assert ev["tenant_id"] == "acme"
    assert ev["entity_id"] == "user-1"
    assert ev["event_type"] == "payment"
    assert ev["payload"]["amount"] == 12.5


def test_heuristic_rejects_unknown_event_type() -> None:
    assert (
        heuristic_map_to_evaluate_request(
            {"tenant_id": "acme", "entity_id": "e1", "event_type": "not_a_type"},
        )
        is None
    )


def test_heuristic_requires_identity() -> None:
    assert heuristic_map_to_evaluate_request({"tenantId": "acme", "type": "login"}) is None
