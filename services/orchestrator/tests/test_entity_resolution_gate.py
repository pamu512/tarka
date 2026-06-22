"""Gate: entity resolution confidence fields on graph viz links."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_ORCH = Path(__file__).resolve().parents[1]
for _p in (_SRC_ORCH,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_build_graph_viz_attaches_resolution_confidence() -> None:
    from entity_profile import build_graph_viz

    network = {
        "found": True,
        "neighbor_node_count": 12,
        "blocked_device_touch_count": 1,
        "network_device_ids": ["device-shared", "device-shared"],
        "network_ip_addresses": ["203.0.113.10"],
        "backend": "janusgraph",
    }
    viz = build_graph_viz("user-anchor", network)
    links = viz["links"]
    assert links, links
    for link in links:
        assert "resolution_confidence" in link
        assert "confidence_label" in link
        assert "confidence_factors" in link
        assert 0.0 <= float(link["resolution_confidence"]) <= 1.0
        assert link["confidence_label"] in ("high", "medium", "low")

    device_links = [link for link in links if link.get("rel") == "USED_DEVICE"]
    ip_links = [link for link in links if link.get("rel") == "ORDERED_FROM_IP"]
    assert device_links and ip_links
    assert float(device_links[0]["resolution_confidence"]) < 0.88
    assert float(ip_links[0]["resolution_confidence"]) <= 0.65
