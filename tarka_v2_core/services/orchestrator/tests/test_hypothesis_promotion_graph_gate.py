"""Gate (Prompt 200): promotion NATS payload marks matched entities ``high_risk`` on JanusGraph."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orchestrator.graph.promotion_hardening import (  # noqa: E402
    apply_promotion_hardening_to_graph,
    read_janus_user_high_risk_values,
)
from orchestrator.workers.hypothesis_promotion_graph import handle_promotion_message  # noqa: E402


class _FakeGremlin:
    def __init__(self) -> None:
        self.marked: dict[str, dict[str, object]] = {}

    def V(self) -> _FakeGremlin:  # noqa: N802
        return self

    def has(self, _label: str, _key: str, user_id: str) -> _FakeGremlin:
        self._uid = user_id
        return self

    def property(self, _cardinality: object, key: str, value: object) -> _FakeGremlin:
        uid = getattr(self, "_uid", "")
        self.marked.setdefault(uid, {})[key] = value
        return self

    def iterate(self) -> None:
        return None

    def values(self, key: str) -> _FakeGremlin:
        self._read_key = key
        return self

    def toList(self) -> list[object]:  # noqa: N802
        uid = getattr(self, "_uid", "")
        val = self.marked.get(uid, {}).get(getattr(self, "_read_key", ""))
        return [val] if val is not None else []


class _FakeJanus:
    def __init__(self) -> None:
        self._g = _FakeGremlin()


def test_apply_promotion_hardening_marks_users_high_risk() -> None:
    janus = _FakeJanus()
    payload = {
        "event": "rule_promoted_to_production",
        "rule_id": "shadow_rule_902",
        "entity_ids": ["user-a", "user-b", ""],
    }
    out = asyncio.run(apply_promotion_hardening_to_graph(janus, payload))  # type: ignore[arg-type]
    assert out["marked"] == 2
    assert janus._g.marked["user-a"]["high_risk"] is True
    assert janus._g.marked["user-a"]["high_risk_rule_id"] == "shadow_rule_902"
    assert read_janus_user_high_risk_values(janus, "user-a") == [True]  # type: ignore[arg-type]


def test_handle_promotion_message_invokes_graph_hardening() -> None:
    janus = _FakeJanus()
    payload = {
        "event": "rule_promoted_to_production",
        "rule_id": "r1",
        "entity_ids": ["ent-1"],
    }
    out = asyncio.run(handle_promotion_message(payload, graph_client=janus))
    assert out["marked"] == 1


def test_handle_promotion_message_rejects_unknown_event() -> None:
    out = asyncio.run(handle_promotion_message({"event": "other"}, graph_client=MagicMock()))
    assert out.get("ok") is False
