"""G1.4: stream + batch L2 writers. Empty FEATURE_STORE_URL = no L2 writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from decision_api.feature_l2 import (
    _STORE,
    backfill_from_jsonl,
    get_features,
    write_event_features,
)


def test_stream_write_readable_at_event_as_of_no_later_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs.test")
    tenant, entity = "t-w-stream", "u-w-stream"
    _STORE.pop((tenant, "user", entity), None)
    t1 = "2026-01-01T00:00:00Z"
    t2 = "2026-06-01T00:00:00Z"
    write_event_features(
        tenant_id=tenant,
        entity_id=entity,
        payload={"amount": 10, "created_at": t1},
    )
    write_event_features(
        tenant_id=tenant,
        entity_id=entity,
        payload={"amount": 99, "created_at": t2},
    )
    at_t1 = get_features(
        tenant_id=tenant, entity_type="user", entity_id=entity, as_of=t1
    )
    before = get_features(
        tenant_id=tenant,
        entity_type="user",
        entity_id=entity,
        as_of="2025-12-01T00:00:00Z",
    )
    at_t2 = get_features(
        tenant_id=tenant, entity_type="user", entity_id=entity, as_of=t2
    )
    assert at_t1.get("amount") == 10
    assert before == {}
    assert at_t2.get("amount") == 99


def test_backfill_from_jsonl_twice_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs.test")
    tenant, entity = "t-w-bf", "u-w-bf"
    _STORE.pop((tenant, "user", entity), None)
    t1 = "2026-01-01T00:00:00Z"
    t2 = "2026-06-01T00:00:00Z"
    path = tmp_path / "export.jsonl"
    path.write_text(
        "\n".join(
            [
                f'{{"tenant_id":"{tenant}","entity_id":"{entity}","as_of":"{t1}","amount":10}}',
                f'{{"tenant_id":"{tenant}","entity_id":"{entity}","as_of":"{t2}","amount":20}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert backfill_from_jsonl(path, tenant_id=tenant) == 2
    assert backfill_from_jsonl(path, tenant_id=tenant) == 2
    assert (
        get_features(
            tenant_id=tenant, entity_type="user", entity_id=entity, as_of=t1
        ).get("amount")
        == 10
    )
    assert (
        get_features(
            tenant_id=tenant, entity_type="user", entity_id=entity, as_of=t2
        ).get("amount")
        == 20
    )
    assert (
        get_features(
            tenant_id=tenant,
            entity_type="user",
            entity_id=entity,
            as_of="2025-12-01T00:00:00Z",
        )
        == {}
    )
    assert len(_STORE.get((tenant, "user", entity)) or []) == 2


def test_empty_feature_store_url_writer_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "")
    tenant, entity = "t-w-off", "u-w-off"
    _STORE.pop((tenant, "user", entity), None)
    write_event_features(
        tenant_id=tenant,
        entity_id=entity,
        payload={"amount": 10, "created_at": "2026-01-01T00:00:00Z"},
    )
    assert (
        get_features(
            tenant_id=tenant,
            entity_type="user",
            entity_id=entity,
            as_of="2026-01-01T00:00:00Z",
        )
        == {}
    )
    assert (tenant, "user", entity) not in _STORE
