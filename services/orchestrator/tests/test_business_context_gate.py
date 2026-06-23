"""Gate: financial DuckDB aggregations require explicit include_business_context=True."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1]
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))

from analytics import business_context as biz_ctx  # noqa: E402


class _UnreachableAnalytics:
    def marketplace_user_stats(self, user_id: str) -> dict[str, object]:
        raise AssertionError(
            "financial aggregation must not run when include_business_context=False"
        )

    def cluster_loss_for_device_hashes(self, device_hashes: object) -> dict[str, object]:
        raise AssertionError(
            "financial aggregation must not run when include_business_context=False"
        )

    def cluster_spend_velocity_for_network(self, **kwargs: object) -> dict[str, object]:
        raise AssertionError(
            "financial aggregation must not run when include_business_context=False"
        )


def test_business_context_skips_financial_aggregations_by_default() -> None:
    analytics = _UnreachableAnalytics()
    skipped = biz_ctx.marketplace_user_stats(analytics, "u1", include_business_context=False)  # type: ignore[arg-type]
    assert skipped["business_context_skipped"] is True
    assert "total_spend" not in skipped

    loss = biz_ctx.cluster_loss_for_device_hashes(
        analytics,  # type: ignore[arg-type]
        ["device-x"],
        include_business_context=False,
    )
    assert loss["business_context_skipped"] is True
    assert loss["cluster_loss"] is None

    velocity = biz_ctx.cluster_spend_velocity_for_network(
        analytics,  # type: ignore[arg-type]
        transaction_entity_ids=[],
        network_user_ids=["u1"],
        include_business_context=False,
    )
    assert velocity["business_context_skipped"] is True


def test_transaction_ingest_never_calls_financial_aggregations() -> None:
    ingest_path = _SRC_ORCH / "transaction_ingest.py"
    source = ingest_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "cluster_loss_for_device_hashes",
        "cluster_spend_velocity_for_network",
        "marketplace_user_stats",
        "include_business_context",
    }
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
    assert forbidden.isdisjoint(
        names
    ), f"transaction_ingest references financial aggregations: {forbidden & names}"
