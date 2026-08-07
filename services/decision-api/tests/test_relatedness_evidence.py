from decision_api.relatedness_evidence import (
    RELATEDNESS_SCHEMA_ID,
    build_relatedness_evidence,
)


def test_graph_peers_only_no_geo_block():
    ev = build_relatedness_evidence(
        tags=["sdk:shared_device"],
        inference_context={},
        location_meta={},
        graph_meta={"seen_at_peer_count_24h": 3},
    )
    assert ev is not None
    assert ev["schema_id"] == RELATEDNESS_SCHEMA_ID
    assert ev["graph"].get("seen_at_peer_count_24h") == 3
    assert "device" in ev
    # geo_enrichment absent or empty — no location_meta risks
    geo = ev.get("geo_enrichment") or {}
    assert not geo.get("copresence_risk")


def test_geo_enrichment_when_location_meta():
    ev = build_relatedness_evidence(
        tags=["location:copresence_elevated"],
        inference_context={"copresence_risk": 0.7},
        location_meta={"copresence_risk": 0.7},
        graph_meta={},
    )
    assert ev["geo_enrichment"]["copresence_risk"] == 0.7
