"""JSON AST → Rego (OPA) transpiler for Tarka visual rules.

Supports nested ``all_of`` / ``any_of``, comparison operators, and set membership.
Unsupported constructs raise :class:`TranspilationError` (no invalid Rego is emitted).
"""

from __future__ import annotations

import json
import re
from typing import Any

_FORBIDDEN_NODE_KEYS = frozenset(
    {
        "macro",
        "macros",
        "fn",
        "func",
        "function",
        "call",
        "lambda",
        "template",
        "import",
        "eval",
    }
)

_SAFE_RULE_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


class TranspilationError(ValueError):
    """Raised when the AST uses a construct that cannot be expressed as safe Rego."""


def _reject_macro_keys(node: dict[str, Any], *, ctx: str) -> None:
    bad = _FORBIDDEN_NODE_KEYS.intersection({k.lower() for k in node})
    if bad:
        raise TranspilationError(f"{ctx}: unsupported AST keys {sorted(bad)}")


def _field_ref(field: str) -> str:
    f = (field or "").strip()
    if not f:
        raise TranspilationError("empty field path")
    if f.startswith("input.") or f.startswith("data.") or f.startswith("object."):
        return f
    return "input." + f


def _rego_string_literal(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _rego_scalar(value: Any) -> str:
    if isinstance(value, (dict, list)):
        raise TranspilationError("scalar value cannot be an object or array")
    if isinstance(value, float) and value != value:
        raise TranspilationError("NaN is not representable as a Rego literal here")
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError as e:
        raise TranspilationError(f"unsupported scalar for Rego literal: {e}") from e


def _rego_set(values: list[Any]) -> str:
    if not values:
        raise TranspilationError("IN / NOT IN requires a non-empty values list")
    if all(isinstance(v, str) for v in values):
        inner = ", ".join(_rego_string_literal(v) for v in values)
        return "{" + inner + "}"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        parts: list[str] = []
        for v in values:
            if isinstance(v, float) and v != v:
                raise TranspilationError("NaN is not allowed in IN / NOT IN sets")
            parts.append(json.dumps(v, ensure_ascii=False))
        return "{" + ", ".join(parts) + "}"
    raise TranspilationError("IN / NOT IN sets must be all strings or all numbers (no booleans)")


def _normalize_op(op: Any) -> str:
    if not isinstance(op, str):
        raise TranspilationError("operator must be a string")
    o = op.strip().lower()
    aliases = {
        "==": "eq",
        "!=": "ne",
        ">": "gt",
        "<": "lt",
        ">=": "gte",
        "<=": "lte",
        "in": "in",
        "not in": "not_in",
        "not_in": "not_in",
    }
    return aliases.get(o, o)


def _emit_leaf(node: dict[str, Any]) -> str:
    _reject_macro_keys(node, ctx="leaf")
    if "all_of" in node or "any_of" in node:
        raise TranspilationError("leaf node cannot contain all_of/any_of")
    allowed_leaf = {"field", "op", "value"}
    extra = set(node) - allowed_leaf
    if extra:
        raise TranspilationError(f"leaf node has unknown keys: {sorted(extra)}")
    if "field" not in node or "op" not in node:
        raise TranspilationError("leaf node requires field and op")
    field = _field_ref(str(node["field"]))
    op = _normalize_op(node["op"])
    val = node.get("value")

    if op in ("contains", "startswith", "endswith", "regex", "matches"):
        raise TranspilationError(f"operator {op!r} is not supported for Rego transpilation")

    if op == "in":
        if not isinstance(val, list):
            raise TranspilationError("IN requires value to be a JSON array")
        return f"{field} in {_rego_set(val)}"

    if op == "not_in":
        if not isinstance(val, list):
            raise TranspilationError("NOT IN requires value to be a JSON array")
        return f"not ({field} in {_rego_set(val)})"

    rhs = _rego_scalar(val)
    if op == "eq":
        return f"{field} == {rhs}"
    if op == "ne":
        return f"{field} != {rhs}"
    if op == "gt":
        return f"{field} > {rhs}"
    if op == "lt":
        return f"{field} < {rhs}"
    if op == "gte":
        return f"{field} >= {rhs}"
    if op == "lte":
        return f"{field} <= {rhs}"

    raise TranspilationError(f"unsupported operator for Rego transpilation: {op!r}")


def _emit_group(node: dict[str, Any], *, kind: str) -> str:
    _reject_macro_keys(node, ctx=kind)
    key = "all_of" if kind == "all" else "any_of"
    allowed = {key}
    extra = set(node) - allowed
    if extra:
        raise TranspilationError(f"{key} group has unknown keys: {sorted(extra)}")
    children = node.get(key)
    if not isinstance(children, list) or not children:
        raise TranspilationError(f"{key} must be a non-empty array")
    parts: list[str] = []
    for i, ch in enumerate(children):
        parts.append(_emit_expr(ch))
    joiner = " and " if kind == "all" else " or "
    if len(parts) == 1:
        return parts[0]
    return "(" + joiner.join(parts) + ")"


def _emit_expr(node: Any) -> str:
    if not isinstance(node, dict):
        raise TranspilationError("expression nodes must be JSON objects")
    _reject_macro_keys(node, ctx="expr")
    if "all_of" in node:
        if "field" in node or "any_of" in node:
            raise TranspilationError("node cannot mix all_of with field/any_of at the same object level")
        return _emit_group(node, kind="all")
    if "any_of" in node:
        if "field" in node or "all_of" in node:
            raise TranspilationError("node cannot mix any_of with field/all_of at the same object level")
        return _emit_group(node, kind="any")
    return _emit_leaf(node)


def _visual_rule_to_ast(rule: dict[str, Any]) -> dict[str, Any]:
    """Combine legacy ``all_of`` / ``any_of`` lists into a single boolean AST."""
    _reject_macro_keys(rule, ctx="rule")
    all_of = rule.get("all_of") or []
    any_of = rule.get("any_of") or []
    if not isinstance(all_of, list) or not isinstance(any_of, list):
        raise TranspilationError("all_of and any_of must be arrays when present")
    chunks: list[dict[str, Any]] = []
    if all_of:
        chunks.append({"all_of": all_of})
    if any_of:
        chunks.append({"any_of": any_of})
    if not chunks:
        raise TranspilationError("rule must include a non-empty all_of and/or any_of")
    if len(chunks) == 1:
        return chunks[0]
    return {"all_of": chunks}


def transpile_visual_rule(rule: dict[str, Any]) -> tuple[str, str]:
    """Return ``(rule_id, condition_expression)`` for one visual rule dict."""
    rid = (rule.get("id") or "").strip()
    if not rid:
        raise TranspilationError("rule id is required")
    if not _SAFE_RULE_ID.match(rid):
        raise TranspilationError(f"rule id must match {_SAFE_RULE_ID.pattern!r}, got {rid!r}")
    ast = _visual_rule_to_ast(rule)
    expr = _emit_expr(ast)
    return rid, expr


def transpile_visual_pack(pack: dict[str, Any]) -> str:
    """Transpile a full visual pack ``{name, rules: [...]}`` into a Rego module string."""
    if not isinstance(pack, dict):
        raise TranspilationError("pack must be a JSON object")
    _reject_macro_keys(pack, ctx="pack")
    rules = pack.get("rules")
    if not isinstance(rules, list) or not rules:
        raise TranspilationError("pack.rules must be a non-empty array")
    lines: list[str] = [
        "package tarka.visual",
        "",
        "import rego.v1",
        "",
    ]
    for rule in rules:
        if not isinstance(rule, dict):
            raise TranspilationError("each rule must be an object")
        rid, expr = transpile_visual_rule(rule)
        lines.append(f'rules contains "{rid}" if {{')
        lines.append(f"    {expr}")
        lines.append("}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
