from graph_service.decision_markings import (
    decision_visible,
    filter_subgraph_for_read,
    parse_caller_markings,
)


def test_no_header_hides_decision():
    node = {
        "id": "dec:1",
        "labels": ["Decision"],
        "properties": {"markings": ["desk"], "outcome": "deny"},
    }
    assert decision_visible(node, parse_caller_markings(None)) is False
    assert decision_visible(node, parse_caller_markings("desk")) is True
    assert decision_visible(node, parse_caller_markings("restricted")) is False


def test_empty_markings_hidden_even_from_desk():
    node = {"id": "dec:2", "labels": ["Decision"], "properties": {"markings": []}}
    assert decision_visible(node, parse_caller_markings("desk")) is False


def test_filter_drops_decision_and_incident_edges():
    data = {
        "nodes": [
            {"id": "buyer", "labels": ["Person"], "properties": {}},
            {
                "id": "dec:secret",
                "labels": ["Decision"],
                "properties": {"markings": ["restricted"]},
            },
            {"id": "dec:desk", "labels": ["Decision"], "properties": {"markings": ["desk"]}},
        ],
        "edges": [
            {"from_id": "buyer", "to_id": "dec:secret", "type": "RESULTED_IN"},
            {"from_id": "buyer", "to_id": "dec:desk", "type": "RESULTED_IN"},
        ],
    }
    out = filter_subgraph_for_read(data, parse_caller_markings("desk"))
    ids = {n["id"] for n in out["nodes"]}
    assert ids == {"buyer", "dec:desk"}
    assert [e["to_id"] for e in out["edges"]] == ["dec:desk"]
