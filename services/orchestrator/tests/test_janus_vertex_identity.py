"""Rungs 1–2: ingest stamps tenant_id + external_id; composite index ensure is in graph-service."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from graph.client import JanusGraphClient
from workers.handlers import graph_ingest


def _tx(**meta: object) -> SimpleNamespace:
    return SimpleNamespace(
        entity_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        amount=1.0,
        timestamp=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
        metadata=dict(meta),
    )


class _RecordingTrav:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self._to_list_n = 0
        self.legacy: object | None = None

    def V(self, *args: object) -> _RecordingTrav:  # noqa: N802
        self.calls.append(("V", args))
        return self

    def has(self, *args: object) -> _RecordingTrav:
        self.calls.append(("has", args))
        return self

    def limit(self, *_args: object) -> _RecordingTrav:
        return self

    def toList(self) -> list[object]:  # noqa: N802
        self._to_list_n += 1
        if self._to_list_n == 1:
            return []
        if self._to_list_n == 2 and self.legacy is not None:
            return [self.legacy]
        return []

    def addV(self, label: str) -> _RecordingTrav:  # noqa: N802
        self.calls.append(("addV", (label,)))
        return self

    def property(self, *args: object) -> _RecordingTrav:
        self.calls.append(("property", args))
        return self

    def next(self) -> str:
        return "NEW_V"

    def iterate(self) -> None:
        return None


def test_merge_stamps_tenant_and_external_id_keeps_native_key() -> None:
    from graph.client import merge_janus_vertex_identity

    g = _RecordingTrav()
    v = merge_janus_vertex_identity(g, "Device", "device_id", "d1", "acme")
    assert v == "NEW_V"
    assert ("has", ("tenant_id", "acme")) in g.calls
    assert ("has", ("external_id", "d1")) in g.calls
    assert ("has", ("Device", "device_id", "d1")) in g.calls
    assert ("addV", ("Device",)) in g.calls
    joined = " ".join(str(x) for kind, args in g.calls if kind == "property" for x in args)
    assert "tenant_id" in joined and "acme" in joined
    assert "external_id" in joined and "d1" in joined
    assert "device_id" in joined


def test_merge_stamps_legacy_vertex() -> None:
    from graph.client import merge_janus_vertex_identity

    g = _RecordingTrav()
    g.legacy = "LEGACY_V"
    v = merge_janus_vertex_identity(g, "Device", "device_id", "d1", "acme")
    assert v == "LEGACY_V"
    assert ("addV", ("Device",)) not in g.calls
    assert ("V", ("LEGACY_V",)) in g.calls
    joined = " ".join(str(x) for kind, args in g.calls if kind == "property" for x in args)
    assert "tenant_id" in joined and "external_id" in joined


def test_merge_email_external_id_is_email() -> None:
    from graph.client import merge_janus_vertex_identity

    g = _RecordingTrav()
    merge_janus_vertex_identity(g, "Email", "email", "alice@acme.com", "acme")
    joined = " ".join(str(x) for kind, args in g.calls if kind == "property" for x in args)
    assert "alice@acme.com" in joined
    assert "external_id" in joined
    assert "email" in joined


def test_ingest_skips_gremlin_when_tenant_missing(caplog: pytest.LogCaptureFixture) -> None:
    merge = MagicMock()
    client = SimpleNamespace(_g=MagicMock())
    with (
        patch.object(graph_ingest, "_merge_vertex", merge),
        patch.object(graph_ingest, "_ensure_connection") as ensure,
        caplog.at_level(logging.INFO, logger="workers.handlers.graph_ingest"),
    ):
        reason = graph_ingest._ingest_janus_sync(
            client,
            _tx(user_id="u1", device_id="d1"),
            audit_log_id=7,
        )
    merge.assert_not_called()
    ensure.assert_not_called()
    assert reason == "noop:no_tenant"
    assert "reason=no_tenant" in caplog.text


def test_ingest_passes_tenant_into_merge() -> None:
    merge = MagicMock(return_value="V")
    client = SimpleNamespace(_g=MagicMock())
    with (
        patch.object(graph_ingest, "_merge_vertex", merge),
        patch.object(graph_ingest, "_ensure_connection"),
        patch.object(graph_ingest, "_ingest_already_committed", return_value=False),
        patch.object(graph_ingest, "_upsert_edge"),
    ):
        graph_ingest._ingest_janus_sync(
            client,
            _tx(tenant_id="acme", user_id="u1", device_id="d1", email="alice@acme.com"),
            audit_log_id=7,
        )
    assert merge.call_count >= 3
    tenants = {c.kwargs.get("tenant_id") for c in merge.call_args_list}
    assert tenants == {"acme"}
    labels = {c.args[1] for c in merge.call_args_list}
    assert "Device" in labels and "Email" in labels and "User" in labels


def test_janus_client_ingest_skips_without_tenant() -> None:
    client = JanusGraphClient(g=MagicMock(), connection=None)
    client._merge_vertex = MagicMock()  # type: ignore[method-assign]
    client._ingest_sync(_tx(user_id="u1", device_id="d1"))
    client._merge_vertex.assert_not_called()
