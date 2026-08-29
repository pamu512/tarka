"""Strict Pydantic models for JSON rule AST payloads (AND/OR + leaf conditions)."""

from __future__ import annotations

import json as _json
from typing import Annotated, Any, Literal, Self

from graph_pack_atoms import GRAPH_V1_ATOMS, refuse_pack_etype_token
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Keep in sync with ``json_rules`` field/value caps for condition leaves.
_MAX_FIELD_LEN = 128
_MAX_VALUE_LEN = 1024
_MAX_CUSTOM_SIGNAL_PARAMS_JSON_BYTES = 8192

MAX_AST_DEPTH = 24
MAX_AST_NODES = 384
MAX_AST_CHILDREN = 32

ConditionOpName = Literal[
    "eq",
    "not_eq",
    "gte",
    "gt",
    "lte",
    "lt",
    "in",
    "not_in",
    "contains",
    "starts_with",
    "ends_with",
    "regex",
    "is_true",
    "is_false",
    "exists",
    "not_exists",
]


class JsonAstCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["condition"] = "condition"
    op: ConditionOpName = "eq"
    field: str = Field(..., min_length=1, max_length=_MAX_FIELD_LEN)
    value: Any = None

    @model_validator(mode="after")
    def _value_len(self) -> Self:
        if self.value is not None and len(str(self.value)) > _MAX_VALUE_LEN:
            raise ValueError("condition.value exceeds maximum serialized length")
        return self


class JsonAstGraphV1(BaseModel):
    """Versioned hop predicate. Consumes ``_graph_hop_v1`` on the feature map."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["graph_v1"] = "graph_v1"
    atom: Literal["has_etype", "has_multi_id", "sibling_prior_flag"]
    etype: str | None = None
    role: str | None = None

    @model_validator(mode="after")
    def _signed_tokens(self) -> Self:
        if self.atom not in GRAPH_V1_ATOMS:
            raise ValueError(f"unknown graph_v1 atom: {self.atom}")
        if self.atom == "has_etype":
            if not (self.etype or "").strip():
                raise ValueError("graph_v1.has_etype requires etype")
            refuse_pack_etype_token(self.etype or "")
        elif self.etype:
            raise ValueError("etype is only valid on graph_v1.has_etype")
        if self.role is not None:
            token = str(self.role).strip()
            if not token:
                raise ValueError("graph_v1.role must be non-empty when set")
            # Format only — tenant lock is evaluated against the hop, not coerced.
            if not token[0].isalpha() or not all(
                ch.isalnum() or ch in "_-" for ch in token
            ):
                raise ValueError(f"unsigned role: {self.role}")
        return self


class JsonAstCustomSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["custom_signal"] = "custom_signal"
    plugin_id: str = Field(..., min_length=1, max_length=_MAX_FIELD_LEN)
    params: dict[str, Any] = Field(default_factory=dict)
    output_key: str = Field(..., min_length=1, max_length=_MAX_FIELD_LEN)

    @model_validator(mode="after")
    def _params_json_cap(self) -> Self:
        try:
            blob = _json.dumps(
                self.params, sort_keys=True, separators=(",", ":")
            ).encode()
        except (TypeError, ValueError) as e:
            raise ValueError("custom_signal.params must be JSON-serializable") from e
        if len(blob) > _MAX_CUSTOM_SIGNAL_PARAMS_JSON_BYTES:
            msg = f"custom_signal.params JSON exceeds {_MAX_CUSTOM_SIGNAL_PARAMS_JSON_BYTES} bytes"
            raise ValueError(msg)
        return self


class JsonAstAnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["and"] = "and"
    children: list[JsonAstNode] = Field(..., min_length=1, max_length=MAX_AST_CHILDREN)


class JsonAstOr(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["or"] = "or"
    children: list[JsonAstNode] = Field(..., min_length=1, max_length=MAX_AST_CHILDREN)


JsonAstNode = Annotated[
    JsonAstCondition | JsonAstCustomSignal | JsonAstGraphV1 | JsonAstAnd | JsonAstOr,
    Field(discriminator="type"),
]


JsonAstAnd.model_rebuild()
JsonAstOr.model_rebuild()


def ast_max_depth(
    node: JsonAstCondition
    | JsonAstAnd
    | JsonAstOr
    | JsonAstCustomSignal
    | JsonAstGraphV1,
) -> int:
    if isinstance(node, (JsonAstCondition, JsonAstCustomSignal, JsonAstGraphV1)):
        return 1
    return 1 + max((ast_max_depth(ch) for ch in node.children), default=0)


def ast_node_count(
    node: JsonAstCondition
    | JsonAstAnd
    | JsonAstOr
    | JsonAstCustomSignal
    | JsonAstGraphV1,
) -> int:
    if isinstance(node, (JsonAstCondition, JsonAstCustomSignal, JsonAstGraphV1)):
        return 1
    return 1 + sum(ast_node_count(ch) for ch in node.children)


def enforce_ast_limits(
    node: JsonAstCondition
    | JsonAstAnd
    | JsonAstOr
    | JsonAstCustomSignal
    | JsonAstGraphV1,
) -> None:
    d = ast_max_depth(node)
    if d > MAX_AST_DEPTH:
        msg = f"AST depth {d} exceeds maximum {MAX_AST_DEPTH}"
        raise ValueError(msg)
    n = ast_node_count(node)
    if n > MAX_AST_NODES:
        msg = f"AST node count {n} exceeds maximum {MAX_AST_NODES}"
        raise ValueError(msg)


class EvaluateAstRequest(BaseModel):
    """Validated body for ``POST /v1/json-rules/evaluate-ast``."""

    model_config = ConfigDict(extra="forbid")

    features: dict[str, Any] = Field(default_factory=dict)
    ast: JsonAstNode
    tenant_id: str | None = None
    entity_id: str | None = None

    @model_validator(mode="after")
    def _check_ast(self) -> Self:
        enforce_ast_limits(self.ast)
        return self


class EvaluateAstResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched: bool
