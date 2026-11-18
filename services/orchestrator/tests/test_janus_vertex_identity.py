"""Rungs 1–2: ingest stamps tenant_id + external_id; composite index ensure is in graph-service."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

from graph.client import JanusGraphClient


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


def test_janus_client_ingest_skips_without_tenant() -> None:
    client = JanusGraphClient(g=MagicMock(), connection=None)
    client._merge_vertex = MagicMock()  # type: ignore[method-assign]
    client._ingest_sync(_tx(user_id="u1", device_id="d1"))
    client._merge_vertex.assert_not_called()
