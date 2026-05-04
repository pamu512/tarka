"""Compile visual-rule AST JSON into deployable JSON rule packs + optional Rego stub (GitOps-ready)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

router = APIRouter(prefix="/v1/rules/visual", tags=["visual-rules"])

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,120}$")


class VisualAstNode(BaseModel):
    """Minimal AST: leaf condition or nested all/any."""

    op: str = Field(..., description="one of: eq, ne, gt, gte, lt, lte, contains")
    field: str = Field(..., max_length=256)
    value: Any = None


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


def _static_check_regex_fields(_: VisualAstPack) -> None:
    """Reject obviously dangerous patterns (ReDoS / pathological size) before compile."""
    # Reserved for regex-based conditions when AST gains pattern ops.
    return


def _compile_to_json_rules(pack: VisualAstPack) -> dict[str, Any]:
    out_rules: list[dict[str, Any]] = []
    for r in pack.rules:
        rid = r.id.strip() or f"visual_{hashlib.sha256(json.dumps(r.model_dump()).encode()).hexdigest()[:10]}"
        if not _SAFE_ID.match(rid):
            raise HTTPException(status_code=400, detail=f"invalid_rule_id:{rid}")
        when: list[dict[str, Any]] = []
        for c in r.all_of:
            when.append({"field": c.field, "op": c.op, "value": c.value})
        for c in r.any_of:
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


def _compile_to_rego_stub(pack: VisualAstPack) -> str:
    """Emit a conservative Rego package stub; extend with full transpilation incrementally."""
    lines = [
        f'package tarka.visual.{re.sub(r"[^a-z0-9_]+", "_", pack.name.lower())[:60]}',
        "default allow = false",
        "allow { count(violations) == 0 }",
        "violations[msg] { false }",
    ]
    for r in pack.rules:
        lines.append(f"# rule {r.id}: {r.description[:80]!r}")
    return "\n".join(lines) + "\n"


@router.post("/compile")
async def compile_visual_ast(
    body: VisualAstPack,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Compile AST → JSON rule pack + Rego stub (Maker/Checker persists artifacts via GitOps)."""
    _static_check_regex_fields(body)
    json_pack = _compile_to_json_rules(body)
    rego = _compile_to_rego_stub(body)
    fp = hashlib.sha256(json.dumps(json_pack, sort_keys=True).encode()).hexdigest()
    return {
        "rule_pack": json_pack,
        "rego_stub": rego,
        "fingerprint_sha256": fp,
        "gitops_note": "Commit rule_pack JSON under rules/visual/ and open PR for peer approval before prod deploy.",
    }
