"""HTTP surface for validating and evaluating JSON rule AST payloads."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends

from tarka_core.engine_adapter import merge_features_with_resolved_from_ast

from decision_api.ast_evaluator import evaluate_json_ast
from decision_api.ast_models import EvaluateAstRequest, EvaluateAstResponse

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

router = APIRouter(prefix="/v1/json-rules", tags=["json-rules"])


@router.post("/evaluate-ast", response_model=EvaluateAstResponse)
async def evaluate_ast_payload(
    body: EvaluateAstRequest,
    _user=Depends(require_role("analyst")),
) -> EvaluateAstResponse:
    """Evaluate a strictly validated AST against a feature map (fail-closed validation on the wire)."""
    tid = (body.tenant_id or "").strip() or "default"
    eid = (body.entity_id or "").strip() or "default"
    merged = merge_features_with_resolved_from_ast(
        body.features,
        body.ast.model_dump(mode="json"),
        tenant_id=tid,
        entity_id=eid,
    )
    return EvaluateAstResponse(matched=evaluate_json_ast(body.ast, merged))
