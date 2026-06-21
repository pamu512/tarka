"""Compile visual-rule AST JSON into deployable JSON rule packs (SR-05)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Any, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

router = APIRouter(prefix="/v1/rules/visual", tags=["visual-rules"])
rego_deprecation_router = APIRouter(prefix="/v1/rules/rego", tags=["rules"])

_REGO_COMPILE_GONE_DETAIL = (
    "Tarka evaluates rules natively via the Rust tarka_rule_engine. "
    "OPA/Rego export is deprecated to ensure auditability and performance."
)

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,120}$")


class VisualAstLeaf(BaseModel):
    """Leaf: ``field`` / ``op`` / ``value``."""

    model_config = ConfigDict(extra="forbid")
    op: str = Field(
        ..., description="one of: eq, ne, gt, gte, lt, lte, in, not_in, ==, etc."
    )
    field: str = Field(..., max_length=256)
    value: Any = None


class VisualAstBranchAll(BaseModel):
    model_config = ConfigDict(extra="forbid")
    all_of: list["VisualAstNode"]


class VisualAstBranchAny(BaseModel):
    model_config = ConfigDict(extra="forbid")
    any_of: list["VisualAstNode"]


VisualAstNode = Annotated[
    Union[VisualAstBranchAll, VisualAstBranchAny, VisualAstLeaf],
    Field(union_mode="left_to_right"),
]


class VisualAstRule(BaseModel):
    id: str = Field(default="", max_length=120)
    all_of: list[VisualAstNode] = Field(default_factory=list)
    any_of: list[VisualAstNode] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    score_delta: float = 0.0
    description: str = Field(default="", max_length=512)


class VisualAstPack(BaseModel):
    name: str = Field(..., max_length=120)
    rules: list[VisualAstRule] = Field(default_factory=list)
    tag_rules: list[dict[str, Any]] = Field(default_factory=list)


class VisualDryRunRequest(BaseModel):
    """Dry-run a canvas pack against a feature map via ``evaluate_adhoc_packs_json`` (no ML/OPA)."""

    model_config = ConfigDict(extra="forbid")
    visual_pack: VisualAstPack
    features: dict[str, Any] = Field(default_factory=dict)
    redis_tags: list[str] = Field(default_factory=list)
    tenant_id: str = Field(default="visual-builder", max_length=128)
    entity_id: str = Field(default="dry-run-entity", max_length=128)


class RuleExprMermaidRequest(BaseModel):
    """RuleExpr JSON (``kind``-tagged union) as serialized by the Rust ``tarka-core`` evaluator."""

    model_config = ConfigDict(extra="forbid")
    rule_expr: dict[str, Any] = Field(
        ...,
        description="Native rule tree: ``kind`` ∈ and | or | not | compare_leaf | …",
    )


class RuleExprMermaidResponse(BaseModel):
    mermaid: str
    format: str = Field(default="mermaid_flowchart_td_v1", max_length=64)


VisualAstBranchAll.model_rebuild()
VisualAstBranchAny.model_rebuild()
VisualAstRule.model_rebuild()
VisualAstPack.model_rebuild()


def _rule_uses_only_flat_leaves(r: VisualAstRule) -> bool:
    """JSON compile path only supports leaves at the rule's ``all_of`` / ``any_of`` lists."""

    def _only_leaves(nodes: list[VisualAstNode]) -> bool:
        return all(isinstance(n, VisualAstLeaf) for n in nodes)

    return _only_leaves(r.all_of) and _only_leaves(r.any_of)


def _static_check_regex_fields(_: VisualAstPack) -> None:
    """Reject obviously dangerous patterns (ReDoS / pathological size) before compile."""
    return


def _compile_to_json_rules(pack: VisualAstPack) -> dict[str, Any]:
    out_rules: list[dict[str, Any]] = []
    for r in pack.rules:
        if not _rule_uses_only_flat_leaves(r):
            raise HTTPException(
                status_code=400,
                detail=(
                    "json_compile_requires_flat_leaves: nested all_of/any_of is not supported for JSON export"
                ),
            )
        rid = (
            r.id.strip()
            or f"visual_{hashlib.sha256(json.dumps(r.model_dump()).encode()).hexdigest()[:10]}"
        )
        if not _SAFE_ID.match(rid):
            raise HTTPException(status_code=400, detail=f"invalid_rule_id:{rid}")
        when: list[dict[str, Any]] = []
        for c in r.all_of:
            assert isinstance(c, VisualAstLeaf)
            when.append({"field": c.field, "op": c.op, "value": c.value})
        for c in r.any_of:
            assert isinstance(c, VisualAstLeaf)
            when.append({"field": c.field, "op": c.op, "value": c.value})
        out_rules.append(
            {
                "id": rid,
                "when": when,
                "tags": r.tags,
                "score_delta": r.score_delta,
                "description": r.description,
            }
        )
    return {
        "name": pack.name,
        "rules": out_rules,
        "tag_rules": pack.tag_rules,
        "compiled_from": "visual_ast_v1",
    }


def compile_visual_ast_pack_dict(body: dict[str, Any]) -> dict[str, Any]:
    """Compile a visual AST pack dict to JSON rule pack fields (for PLG bootstrap / CI).

    Raises ``ValueError`` on validation or unsupported nesting (same rules as HTTP compile).
    """
    try:
        pack = VisualAstPack.model_validate(body)
    except Exception as e:
        raise ValueError(f"invalid_visual_ast_pack:{e}") from e
    try:
        return _compile_to_json_rules(pack)
    except HTTPException as e:
        detail = e.detail
        if isinstance(detail, dict):
            raise ValueError(str(detail)) from e
        raise ValueError(str(detail)) from e


@router.post("/evaluate-dry-run")
async def evaluate_visual_dry_run(
    body: VisualDryRunRequest,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Compile visual AST to JSON ``when`` rules, then evaluate ad-hoc pack in simulation."""
    from decision_api.json_rules import evaluate_adhoc_packs_json

    if not body.visual_pack.rules:
        raise HTTPException(
            status_code=400, detail="visual_pack.rules must be non-empty"
        )
    _static_check_regex_fields(body.visual_pack)
    json_pack = _compile_to_json_rules(body.visual_pack)
    pack: dict[str, Any] = {
        "version": 1,
        "mode": "active",
        "name": json_pack["name"],
        "rules": json_pack["rules"],
        "tag_rules": json_pack.get("tag_rules") or [],
        "_source_file": "visual_dry_run.json",
    }
    hits, tags, delta, _ = evaluate_adhoc_packs_json(
        [pack],
        body.features,
        body.redis_tags,
        tenant_id=body.tenant_id,
        entity_id=body.entity_id,
        evaluation_mode="simulation",
        record_telemetry=False,
    )
    return {
        "rule_hits": hits,
        "tags": tags,
        "score_delta": delta,
        "compiled_rules": json_pack["rules"],
    }


@router.post("/mermaid")
async def rule_expr_to_mermaid_diagram(
    body: RuleExprMermaidRequest,
    _user=Depends(require_role("analyst")),
) -> RuleExprMermaidResponse:
    """Turn a ``RuleExpr`` JSON tree into Mermaid flowchart text (Rust ``tarka-core`` renderer via ``tarka`` PyO3)."""
    raw = json.dumps(body.rule_expr, separators=(",", ":"))
    try:
        from tarka.decision import rule_expr_mermaid_flowchart
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Install the `tarka` package (PyO3 bindings to tarka-core, built from crates/tarka-py) "
                "to generate RuleExpr diagrams."
            ),
        ) from None
    try:
        diagram = rule_expr_mermaid_flowchart(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RuleExprMermaidResponse(mermaid=diagram)


@router.post("/compile")
async def compile_visual_ast(
    body: VisualAstPack,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Compile AST → JSON rule pack."""
    _static_check_regex_fields(body)
    json_pack = _compile_to_json_rules(body)
    fp = hashlib.sha256(json.dumps(json_pack, sort_keys=True).encode()).hexdigest()
    return {
        "rule_pack": json_pack,
        "fingerprint_sha256": fp,
        "gitops_note": "Commit rule_pack JSON under rules/visual/ and open PR for peer approval before prod deploy.",
    }


@rego_deprecation_router.post(
    "/compile",
    deprecated=True,
    summary="OPA/Rego compile (removed)",
    description="Returns 410 Gone. Rule compilation is JSON-only; use POST /v1/rules/visual/compile.",
    response_model=None,
)
async def compile_rego_deprecated_410(_user=Depends(require_role("analyst"))) -> None:
    raise HTTPException(status_code=410, detail=_REGO_COMPILE_GONE_DETAIL)
