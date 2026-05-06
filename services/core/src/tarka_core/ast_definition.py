"""JSON AST shape contracts for Tarka rules (stdlib TypedDicts; validate in services with Pydantic).

``custom_signal`` nodes declare analyst-defined Python plugins that resolve to scalar features
before the rule engine (Rust or Python) evaluates ``condition`` leaves. See
:class:`tarka_core.engine_adapter.SignalResolver`.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class CustomSignalAstDict(TypedDict):
    """Leaf node: resolve ``plugin_id`` with ``params``, inject ``output_key`` into the feature map."""

    type: str  # "custom_signal"
    plugin_id: str
    params: NotRequired[dict[str, Any]]
    output_key: str


class JsonAstConditionDict(TypedDict, total=False):
    type: str
    op: str
    field: str
    value: Any


class JsonAstCompositeDict(TypedDict, total=False):
    type: str
    children: list[JsonAstNodeDict]


JsonAstNodeDict = JsonAstConditionDict | JsonAstCompositeDict | CustomSignalAstDict
