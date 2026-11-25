"""GRAPH_INGEST posts graph_contract objects and does not open Gremlin."""

from __future__ import annotations

from pathlib import Path


def test_graph_ingest_posts_contract_objects_and_skips_email() -> None:
    from workers.handlers.graph_ingest import posts_for_hints

    body_list = posts_for_hints(
        {
            "tenant_id": "acme",
            "user_id": "u1",
            "device_id": "d1",
            "ip": "203.0.113.9",
            "card_id": "card-9",
            "email": "a@example.com",
            "address": "1 Main",
        }
    )
    kinds = {(b["mapping"]["object_type"], b["mapping"]["relationship"]) for b in body_list}
    assert kinds == {("device", "USED_DEVICE"), ("ip", "USED_IP"), ("payment", "MADE_PAYMENT")}
    assert all(b["tenant_id"] == "acme" for b in body_list)


def test_graph_ingest_handler_does_not_open_gremlin() -> None:
    text = (
        Path(__file__).resolve().parents[1] / "workers" / "handlers" / "graph_ingest.py"
    ).read_text()
    assert "_connect_janusgraph" not in text
    assert "JanusGraphClient" not in text
