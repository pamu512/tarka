"""REST API for rule CRUD — serves the visual rule builder."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from decision_api.config import settings
from decision_api.json_rules import load_rules
from decision_api.shadow import get_observation_stats, get_observations, load_shadow_rules
from decision_api.vertical_packs import get_vertical_pack, list_vertical_packs

router = APIRouter(prefix="/v1/rules", tags=["rules"])
_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,120}\.json$")


class Condition(BaseModel):
    field: str
    op: str = "eq"
    value: Any = None


class RuleIn(BaseModel):
    id: str = ""
    when: list[Condition] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    score_delta: float = 0
    description: str = ""


class TagRuleIn(BaseModel):
    id: str = ""
    any_tag: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    score_delta: float = 0
    description: str = ""


class RulePackIn(BaseModel):
    name: str
    rules: list[RuleIn] = Field(default_factory=list)
    tag_rules: list[TagRuleIn] = Field(default_factory=list)


def _rules_dir() -> Path:
    p = Path(settings.rules_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_path(filename: str) -> Path:
    """Resolve filename within rules dir, rejecting path traversal."""
    if not _SAFE_FILENAME_RE.fullmatch(filename):
        raise HTTPException(400, "invalid filename")
    base = _rules_dir().resolve()
    target = (base / filename).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(400, "invalid filename")
    return target


def _read_all_packs() -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    d = _rules_dir()
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_file"] = f.name
            packs.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return packs


def _validate_rule_pack(pack: dict) -> list[str]:
    """Validate a rule pack and return list of errors."""
    errors = []
    rules = pack.get("rules", [])
    if len(rules) > 200:
        errors.append(f"Too many rules: {len(rules)} (max 200)")
    for i, rule in enumerate(rules):
        rid = rule.get("id", f"rule_{i}")
        conditions = rule.get("when", [])
        if len(conditions) > 20:
            errors.append(f"Rule {rid}: too many conditions ({len(conditions)}, max 20)")
        for j, c in enumerate(conditions):
            if not c.get("field"):
                errors.append(f"Rule {rid}, condition {j}: missing 'field'")
            if c.get("op") == "regex":
                pattern = str(c.get("value", ""))
                if len(pattern) > 256:
                    errors.append(f"Rule {rid}, condition {j}: regex pattern too long")
        sd = rule.get("score_delta", 0)
        if abs(float(sd)) > 100:
            errors.append(f"Rule {rid}: score_delta {sd} exceeds bounds (-100, 100)")
    return errors


@router.get("")
async def list_rule_packs():
    return {"packs": _read_all_packs()}


@router.get("/vertical-packs")
async def list_vertical_pack_catalog():
    return {"vertical_packs": list_vertical_packs()}


@router.post("/vertical-packs/{vertical_name}/install", status_code=201)
async def install_vertical_pack(vertical_name: str, overwrite: bool = False):
    pack = get_vertical_pack(vertical_name)
    if not pack:
        raise HTTPException(404, f"unknown vertical pack '{vertical_name}'")
    fname = f"vertical_{vertical_name.lower()}.json"
    fpath = _safe_path(fname)
    if fpath.exists() and not overwrite:
        raise HTTPException(409, f"pack '{fname}' already exists; pass overwrite=true to replace")
    errors = _validate_rule_pack(pack)
    if errors:
        raise HTTPException(422, detail={"validation_errors": errors})
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    return {"installed": fname, "vertical": vertical_name.lower(), "rules": len(pack.get("rules", []))}


@router.get("/{filename}")
async def get_rule_pack(filename: str):
    fpath = _safe_path(filename)
    if not fpath.exists():
        raise HTTPException(404, "pack not found")
    data = json.loads(fpath.read_text(encoding="utf-8"))
    data["_file"] = filename
    return data


@router.post("", status_code=201)
async def create_rule_pack(body: RulePackIn):
    fname = body.name.replace(" ", "_").lower() + ".json"
    fpath = _safe_path(fname)
    if fpath.exists():
        raise HTTPException(409, f"pack '{fname}' already exists")
    pack = {
        "version": 1,
        "name": body.name,
        "rules": [_rule_to_dict(r) for r in body.rules],
        "tag_rules": [_tag_rule_to_dict(r) for r in body.tag_rules],
    }
    errors = _validate_rule_pack(pack)
    if errors:
        raise HTTPException(422, detail={"validation_errors": errors})
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    return {"file": fname, "pack": pack}


@router.put("/{filename}")
async def update_rule_pack(filename: str, body: RulePackIn):
    fpath = _safe_path(filename)
    if not fpath.exists():
        raise HTTPException(404, "pack not found")
    pack = {
        "version": 1,
        "name": body.name,
        "rules": [_rule_to_dict(r) for r in body.rules],
        "tag_rules": [_tag_rule_to_dict(r) for r in body.tag_rules],
    }
    errors = _validate_rule_pack(pack)
    if errors:
        raise HTTPException(422, detail={"validation_errors": errors})
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    return {"file": filename, "pack": pack}


@router.delete("/{filename}")
async def delete_rule_pack(filename: str):
    fpath = _safe_path(filename)
    if not fpath.exists():
        raise HTTPException(404, "pack not found")
    fpath.unlink()
    load_rules()
    return {"deleted": filename}


@router.post("/{filename}/rules")
async def add_rule(filename: str, body: RuleIn):
    fpath = _safe_path(filename)
    if not fpath.exists():
        raise HTTPException(404, "pack not found")
    pack = json.loads(fpath.read_text(encoding="utf-8"))
    if not body.id:
        body.id = f"rule_{uuid.uuid4().hex[:8]}"
    pack.setdefault("rules", []).append(_rule_to_dict(body))
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    return {"added": body.id}


class RulePackMode(BaseModel):
    mode: str


@router.put("/{filename}/mode")
async def set_pack_mode(filename: str, body: RulePackMode):
    """Set a rule pack to active, shadow, or disabled mode."""
    fpath = _safe_path(filename)
    if not fpath.exists():
        raise HTTPException(404, "pack not found")
    if body.mode not in ("active", "shadow", "disabled"):
        raise HTTPException(400, "mode must be 'active', 'shadow', or 'disabled'")
    pack = json.loads(fpath.read_text(encoding="utf-8"))
    pack["mode"] = body.mode
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    return {"file": filename, "mode": body.mode}


@router.delete("/{filename}/rules/{rule_id}")
async def remove_rule(filename: str, rule_id: str):
    fpath = _safe_path(filename)
    if not fpath.exists():
        raise HTTPException(404, "pack not found")
    pack = json.loads(fpath.read_text(encoding="utf-8"))
    original = len(pack.get("rules", []))
    pack["rules"] = [r for r in pack.get("rules", []) if r.get("id") != rule_id]
    if len(pack["rules"]) == original:
        raise HTTPException(404, f"rule '{rule_id}' not found")
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    return {"deleted": rule_id}


@router.post("/shadow/reload")
async def reload_shadow_rules():
    load_shadow_rules()
    return {"ok": True}


@router.get("/shadow/observations")
async def shadow_observations(limit: int = 100):
    return {"observations": get_observations(limit)}


@router.get("/shadow/stats")
async def shadow_stats():
    return get_observation_stats()


def _rule_to_dict(r: RuleIn) -> dict[str, Any]:
    return {
        "id": r.id or f"rule_{uuid.uuid4().hex[:8]}",
        "when": [{"field": c.field, "op": c.op, "value": c.value} for c in r.when],
        "tags": r.tags,
        "score_delta": r.score_delta,
        "description": r.description,
    }


def _tag_rule_to_dict(r: TagRuleIn) -> dict[str, Any]:
    return {
        "id": r.id or f"tagrule_{uuid.uuid4().hex[:8]}",
        "any_tag": r.any_tag,
        "tags": r.tags,
        "score_delta": r.score_delta,
        "description": r.description,
    }
