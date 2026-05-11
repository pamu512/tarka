"""Unit tests: ``TransactionSchema`` → :class:`~orchestrator.graph.client.GraphHints`."""

from __future__ import annotations

import sys
from typing import Any
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ingestor.manifest_schema import TransactionSchema  # noqa: E402
from orchestrator.graph.client import graph_hints_from_transaction  # noqa: E402


def _txn(**meta: Any) -> TransactionSchema:
    return TransactionSchema(
        entity_id=UUID("11111111-1111-1111-1111-111111111111"),
        amount=10.0,
        timestamp=datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC),
        metadata=dict(meta),
    )


def test_graph_hints_resolves_user_ip_and_device() -> None:
    h = graph_hints_from_transaction(_txn(user_id="u1", ip="10.0.0.1", device_id="d-9"))
    assert h.user_id == "u1"
    assert h.ip == "10.0.0.1"
    assert h.device_id == "d-9"
    assert h.any() is True


def test_graph_hints_graph_user_is_blocked_flag() -> None:
    h = graph_hints_from_transaction(
        _txn(user_id="u1", graph_user_is_blocked=True),
    )
    assert h.user_id == "u1"
    assert h.user_marked_blocked is True


def test_graph_hints_accepts_graph_prefixed_keys() -> None:
    h = graph_hints_from_transaction(_txn(graph_user_id="u2", graph_ip="192.168.1.1"))
    assert h.user_id == "u2"
    assert h.ip == "192.168.1.1"


def test_graph_hints_order_and_passport_metadata() -> None:
    h = graph_hints_from_transaction(
        _txn(order_id="ORD-XYZ-9", passport_id="P9876543", graph_order_id="ignored-when-order_id"),
    )
    assert h.order_id == "ORD-XYZ-9"
    assert h.passport_id == "P9876543"


def test_graph_hints_listing_id_metadata() -> None:
    h = graph_hints_from_transaction(
        _txn(listing_id="LST-100", user_id="u1"),
    )
    assert h.listing_id == "LST-100"
    h2 = graph_hints_from_transaction(_txn(review_listing_id="LST-200"))
    assert h2.listing_id == "LST-200"
    h3 = graph_hints_from_transaction(_txn(marketplace_listing_id="LST-300"))
    assert h3.listing_id == "LST-300"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        " " * 3,
        "x" * 600,
        "a\x00b",
    ],
)
def test_graph_hints_rejects_bad_strings(bad: str) -> None:
    h = graph_hints_from_transaction(_txn(user_id=bad))
    assert h.user_id is None
