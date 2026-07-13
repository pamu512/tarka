from graph_service.entity_context_shape import shape_deep_context_from_nodes


def test_shape_extracts_payment_and_ip_property():
    nodes = [
        {
            "id": "u1",
            "labels": ["Person"],
            "properties": {"name": "x"},
        },
        {
            "id": "pay1",
            "labels": ["Payment"],
            "properties": {
                "trace_id": "tr-1",
                "amount": 99.5,
                "currency": "USD",
                "decision": "review",
                "client_ip": "10.0.0.1",
            },
        },
    ]
    out = shape_deep_context_from_nodes("u1", "demo", nodes)
    assert out["entity_id"] == "u1"
    assert len(out["historical_transactions"]) == 1
    assert out["historical_transactions"][0]["trace_id"] == "tr-1"
    assert len(out["ip_addresses"]) == 1
    assert out["ip_addresses"][0]["ip"] == "10.0.0.1"


def test_shape_ip_vertex_external_id():
    nodes = [{"id": "203.0.113.7", "labels": ["Custom"], "properties": {}}]
    out = shape_deep_context_from_nodes("root", "t", nodes)
    assert out["ip_addresses"][0]["ip"] == "203.0.113.7"
