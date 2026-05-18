"""Unit tests for review ring clusters (Prompt 185)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "review_ring_clusters.py"
_spec = importlib.util.spec_from_file_location("review_ring_clusters", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["review_ring_clusters"] = _mod
_spec.loader.exec_module(_mod)


def test_clusters_have_five_shared_products() -> None:
    payload = _mod.build_review_ring_payload(tenant_id="demo", limit=8)
    assert payload["rules"]["shared_product_count"] == 5
    assert payload["clusters"]
    cluster = payload["clusters"][0]
    assert len(cluster["shared_products"]) == 5
    assert len(cluster["shared_product_ids"]) == 5
    for member in cluster["members"]:
        assert member["shared_product_count"] == 5
        assert len(member["reviews"]) == 5


def test_min_ring_size_filter() -> None:
    payload = _mod.build_review_ring_payload(tenant_id="demo", min_ring_size=4, limit=10)
    assert all(int(c["member_count"]) >= 4 for c in payload["clusters"])


def test_exact_overlap_signal() -> None:
    payload = _mod.build_review_ring_payload(tenant_id="demo", limit=3)
    assert "exact_five_product_review_overlap" in payload["clusters"][0]["signals"]
