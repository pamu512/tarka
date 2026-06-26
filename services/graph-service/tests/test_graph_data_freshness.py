from graph_data_freshness import graph_data_as_of_iso


def test_graph_data_as_of_picks_latest():
    iso = graph_data_as_of_iso(
        {
            "updated_at": "2026-06-01T10:00:00Z",
            "last_seen": "2026-06-25T12:00:00Z",
        }
    )
    assert iso == "2026-06-25T12:00:00Z"


def test_graph_data_as_of_missing_returns_none():
    assert graph_data_as_of_iso({}) is None
