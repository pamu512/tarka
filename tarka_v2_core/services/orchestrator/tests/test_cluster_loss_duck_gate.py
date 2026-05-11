"""Gate (Prompt 123): DuckDB cluster loss sums amounts across all accounts for device-linked sessions."""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_cluster_loss_matches_device_hash_and_coalesced_device_keys() -> None:
    from ingestor.manifest_schema import TransactionSchema  # noqa: PLC0415
    from orchestrator.analytics.duck_provider import DuckAnalyticsProvider  # noqa: PLC0415

    dh = "a1b2c3d4e5f6deadbeef00devicehashgate123"
    duck = DuckAnalyticsProvider()
    duck.load()
    duck.append_transaction(
        TransactionSchema(
            entity_id=uuid.uuid4(),
            amount=30.0,
            timestamp=datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC),
            metadata={"device_hash": dh, "session_id": "s-root", "user_id": "u-disputed"},
        ),
    )
    duck.append_transaction(
        TransactionSchema(
            entity_id=uuid.uuid4(),
            amount=70.0,
            timestamp=datetime(2026, 8, 1, 10, 1, 0, tzinfo=UTC),
            metadata={"user_id": "u-peer", "session_id": "s-root"},
        ),
    )
    r1 = duck.cluster_loss_by_device_hash(dh)
    assert r1["cluster_loss"] == pytest.approx(100.0)
    assert r1["linked_txn_count"] == 2
    assert r1["distinct_session_count"] == 1

    duck.append_transaction(
        TransactionSchema(
            entity_id=uuid.uuid4(),
            amount=5.0,
            timestamp=datetime(2026, 8, 1, 11, 0, 0, tzinfo=UTC),
            metadata={"graph_device_id": dh.upper(), "linked_session_id": "s-side"},
        ),
    )
    duck.append_transaction(
        TransactionSchema(
            entity_id=uuid.uuid4(),
            amount=15.0,
            timestamp=datetime(2026, 8, 1, 11, 1, 0, tzinfo=UTC),
            metadata={"device_fingerprint": dh, "device_session_id": "s-side"},
        ),
    )
    r2 = duck.cluster_loss_for_device_hashes([dh])
    assert r2["cluster_loss"] == pytest.approx(120.0)
    assert r2["distinct_session_count"] == 2
    assert r2["linked_txn_count"] == 4
