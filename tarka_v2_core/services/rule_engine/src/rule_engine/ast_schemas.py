"""Pydantic AST primitives for transaction rule conditions.

Field names include :class:`ingestor.manifest_schema.TransactionSchema` columns plus
rule-engine extensions such as ``country`` when the ingestion model gains derived fields.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self, TypeAlias, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Operator(StrEnum):
    """Wire-stable string enum for rule operators (values are exactly ``EQ``, ``GT``, …)."""

    EQ = "EQ"
    GT = "GT"
    LT = "LT"
    CONTAINS = "CONTAINS"


TransactionSchemaField: TypeAlias = Literal[
    "entity_id",
    "amount",
    "timestamp",
    "metadata",
    "country",
]


class FieldRef(BaseModel):
    """Reference to one field exposed on the canonical transaction envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: Annotated[
        TransactionSchemaField,
        Field(description="Public field name on TransactionSchema"),
    ]


ScalarLiteral: TypeAlias = bool | int | float | str | None


class Value(BaseModel):
    """Literal RHS for comparisons (scalar, datetime, or shallow JSON-like structures)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    literal: Annotated[
        ScalarLiteral | datetime | dict[str, Any] | list[Any],
        Field(description="Literal value compared against a FieldRef"),
    ]


class ConditionNode(BaseModel):
    """Single predicate: field reference, operator, and RHS literal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: FieldRef
    operator: Operator
    value: Any

    @model_validator(mode="after")
    def validate_value_matches_operator(self) -> Self:
        """Reject RHS types that cannot sensibly pair with the operator (Pydantic v2 ``model_validator``)."""
        op = self.operator
        v = self.value

        if op in (Operator.GT, Operator.LT):
            if isinstance(v, bool):
                raise ValueError("GT and LT do not accept boolean values (ambiguous with integers).")
            if isinstance(v, str):
                raise ValueError("GT and LT require a numeric or datetime literal, not a string.")
            if not isinstance(v, (int, float, datetime)):
                raise ValueError(
                    "GT and LT only accept int, float, or datetime literals on the right-hand side.",
                )
            return self

        if op == Operator.CONTAINS:
            if not isinstance(v, str):
                raise ValueError("CONTAINS requires a string literal on the right-hand side.")
            return self

        # EQ: no structural restriction on ``value``.
        return self


class AndNode(BaseModel):
    """Logical AND over two or more child nodes (conditions or nested groups)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    children: Annotated[
        list[Union["ConditionNode", "AndNode", "OrNode"]],
        Field(min_length=2, description="Conjuncts; may nest ``AndNode`` / ``OrNode`` arbitrarily."),
    ]


class OrNode(BaseModel):
    """Logical OR over two or more child nodes (conditions or nested groups)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    children: Annotated[
        list[Union["ConditionNode", "AndNode", "OrNode"]],
        Field(min_length=2, description="Disjuncts; may nest ``AndNode`` / ``OrNode`` arbitrarily."),
    ]


LogicalNode: TypeAlias = ConditionNode | AndNode | OrNode

AndNode.model_rebuild()
OrNode.model_rebuild()


class Action(StrEnum):
    """Wire-stable outcome when a rule's predicate matches a transaction."""

    FLAG = "FLAG"
    BLOCK = "BLOCK"
    ALLOW = "ALLOW"
    SHADOW_REVIEW = "SHADOW_REVIEW"


class Rule(BaseModel):
    """Named rule: logical ``root_node``, enforced ``action``, and ``priority`` for ordering."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[UUID, Field(description="Stable rule identifier")]
    name: Annotated[str, Field(min_length=1, description="Human-readable rule name")]
    root_node: Annotated[
        LogicalNode,
        Field(description="Root predicate: condition or nested AND/OR group"),
    ]
    action: Action
    priority: Annotated[
        int,
        Field(description="Relative ordering vs other rules (semantics defined by the engine)."),
    ]
