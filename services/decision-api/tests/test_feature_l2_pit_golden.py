"""G1.5: golden PIT replay at T + holdout (offline). Model never decides."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from decision_api.feature_l2 import (
    _STORE,
    evaluate_l2_read,
    get_features,
    holdout_split,
    upsert_feature,
)
from event_time import parse_event_time_to_unix

_REPO = Path(__file__).resolve().parents[3]
_CLAIM_LOCK = _REPO / "docs" / "compliance" / "CLAIM_LOCK.md"
_FLOWS = _REPO / "docs" / "docs" / "guides" / "feature-data-flows.md"
_POSTURE = _REPO / "docs" / "contracts" / "feature-store-posture-v1.md"

# Fractional ISO sorts before `Z`; wall time is later. String sort would leak.
T1 = "2026-01-01T10:00:00Z"
T2 = "2026-01-01T10:00:00.500Z"
TENANT = "t-g15-golden"
ENTITY = "u-g15-golden"
FROZEN_T1 = {"amount": 10, "event_count_1h": 1}
LATER_T2 = {"amount": 99, "event_count_1h": 9}


def _clear() -> None:
    _STORE.pop((TENANT, "user", ENTITY), None)


def test_golden_pit_replay_as_of_t1_matches_frozen_no_future_leak() -> None:
    _clear()
    upsert_feature(
        tenant_id=TENANT,
        entity_type="user",
        entity_id=ENTITY,
        features=dict(FROZEN_T1),
        as_of=T1,
    )
    frozen = get_features(
        tenant_id=TENANT, entity_type="user", entity_id=ENTITY, as_of=T1
    )
    assert frozen == FROZEN_T1
    upsert_feature(
        tenant_id=TENANT,
        entity_type="user",
        entity_id=ENTITY,
        features=dict(LATER_T2),
        as_of=T2,
    )
    replay = get_features(
        tenant_id=TENANT, entity_type="user", entity_id=ENTITY, as_of=T1
    )
    assert replay == frozen == FROZEN_T1
    assert replay.get("amount") != LATER_T2["amount"]
    later = get_features(
        tenant_id=TENANT, entity_type="user", entity_id=ENTITY, as_of=T2
    )
    assert later == LATER_T2


@pytest.mark.asyncio
async def test_golden_pit_evaluate_l2_read_matches_t1_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear()
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs.test")
    upsert_feature(
        tenant_id=TENANT,
        entity_type="user",
        entity_id=ENTITY,
        features=dict(FROZEN_T1),
        as_of=T1,
    )
    upsert_feature(
        tenant_id=TENANT,
        entity_type="user",
        entity_id=ENTITY,
        features=dict(LATER_T2),
        as_of=T2,
    )
    frozen = get_features(
        tenant_id=TENANT, entity_type="user", entity_id=ENTITY, as_of=T1
    )

    async def _get(_url, **kwargs):
        params = kwargs.get("params") or {}
        feats = get_features(
            tenant_id=str(params.get("tenant_id") or ""),
            entity_type="user",
            entity_id=ENTITY,
            as_of=params.get("as_of"),
        )
        return SimpleNamespace(status_code=200, json=lambda: {"features": feats})

    http = SimpleNamespace(get=_get)
    feats, source = await evaluate_l2_read(
        http,
        tenant_id=TENANT,
        entity_id=ENTITY,
        as_of=T1,
        redis_url="redis://localhost:6379/0",
    )
    assert source == "l2"
    assert feats == frozen == FROZEN_T1
    assert feats.get("amount") != LATER_T2["amount"]


@pytest.mark.asyncio
async def test_golden_pit_empty_url_evaluate_l2_read_not_fake_l2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("TARKA_REDIS_URL", raising=False)
    http = SimpleNamespace(get=None)
    feats, source = await evaluate_l2_read(
        http,
        tenant_id=TENANT,
        entity_id=ENTITY,
        as_of=T1,
        redis_url="",
    )
    assert feats is None
    assert source in {"l1", "raw"}
    assert source != "l2"


def test_holdout_split_training_excludes_as_of_at_or_after_cutoff() -> None:
    """Later fractional ISO must not enter train (string sort would leak T2)."""
    rows = [
        {"as_of": T1, "id": "t1"},
        {"as_of": T2, "id": "t2"},
    ]
    cutoff = T1
    cut_ts = parse_event_time_to_unix(cutoff)
    assert cut_ts is not None
    train, hold = holdout_split(rows, cutoff=cutoff)
    assert [r["id"] for r in train] == []
    assert {r["id"] for r in hold} == {"t1", "t2"}
    for row in train:
        row_ts = parse_event_time_to_unix(row.get("as_of"))
        assert row_ts is not None
        assert row_ts < cut_ts


def test_holdout_split_iso_later_fraction_stays_out_of_train() -> None:
    rows = [
        {"as_of": "2026-01-01T09:00:00Z", "id": "early"},
        {"as_of": T1, "id": "at-cut"},
        {"as_of": T2, "id": "later"},
    ]
    train, hold = holdout_split(rows, cutoff=T1)
    assert [r["id"] for r in train] == ["early"]
    assert [r["id"] for r in hold] == ["at-cut", "later"]


def test_claim_lock_pit_holdout_honesty_both_sides() -> None:
    lock = _CLAIM_LOCK.read_text(encoding="utf-8")
    flows = _FLOWS.read_text(encoding="utf-8")
    posture = _POSTURE.read_text(encoding="utf-8")
    assert "frozen features" in lock
    assert "no future leak" in lock
    assert "holdout_split" in lock
    assert "sidecar" in lock.lower() or "offline" in lock.lower()
    assert "as_of >= cutoff" in lock
    assert "model never" in lock.lower()
    assert "ALLOW/DENY" in lock
    assert "Feast" in lock or "feast_class_claim_allowed" in lock
    assert "GNN live" in lock
    assert "frozen features" in flows
    assert "holdout_split" in flows
    assert "offline" in flows.lower()
    assert "model never" in flows.lower() or "never ALLOW/DENY" in flows
    assert "feast_class_claim_allowed" in flows
    assert "false" in posture.lower()
    assert "feast_class_claim_allowed" in posture


def test_gnn_url_unset_stays_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRAPH_GNN_BETA_URL", raising=False)
    from decision_api.gnn_loop.readiness import compute_graph_risk_readiness

    out = compute_graph_risk_readiness(
        tenant_id="acme",
        receipts=[],
        labeled_rows=[],
        graph_service_url="",
        graph_gnn_beta_url="",
        gate=None,
    )
    assert out["gnn_claim_allowed"] is False
    assert out["overlay_url"] == "empty"
    assert "GNN live" not in out["display_name"]
