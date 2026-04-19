"""REST API for rule CRUD — serves the visual rule builder."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from decision_api.config import settings
from decision_api.json_rules import load_rules
from decision_api.rule_pack_validation import validate_rule_pack as _validate_rule_pack
from decision_api.shadow import get_observation_stats, get_observations, load_shadow_rules
from decision_api.vertical_packs import get_vertical_pack, list_vertical_packs

router = APIRouter(prefix="/v1/rules", tags=["rules"])
_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,120}\.json$")
_SAFE_SLUG_RE = re.compile(r"[^a-z0-9_-]+")

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402


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
    canary_percent: float | None = Field(default=None, ge=0, le=100)
    effective_at: str | None = Field(default=None, max_length=64)
    approved_by: str | None = Field(default=None, max_length=256)


def _rules_dir() -> Path:
    p = Path(settings.rules_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _change_log_path() -> Path:
    return _rules_dir() / "rule_change_log.jsonl"


def _append_rule_change(
    action: str,
    filename: str,
    *,
    actor: str = "api",
    detail: dict[str, Any] | None = None,
) -> None:
    """Append-only audit for lightweight governance (not a full CMDB)."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "file": filename,
        "actor": actor,
        "detail": detail or {},
    }
    p = _change_log_path()
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def _list_pack_paths() -> dict[str, Path]:
    base = _rules_dir()
    return {p.name: p for p in base.glob("*.json") if p.is_file()}


def _existing_pack_path(filename: str) -> Path:
    if not _SAFE_FILENAME_RE.fullmatch(filename):
        raise HTTPException(400, "invalid filename")
    path = _list_pack_paths().get(filename)
    if not path:
        raise HTTPException(404, "pack not found")
    return path


def _slugify_pack_name(name: str) -> str:
    raw = name.strip().lower().replace(" ", "_")
    slug = _SAFE_SLUG_RE.sub("", raw)
    slug = slug.strip("._-")
    if not slug:
        raise HTTPException(400, "invalid pack name")
    return slug[:80]


def _new_pack_path(prefix: str = "pack") -> Path:
    # Avoid any user-controlled filesystem path fragments.
    return _rules_dir() / f"{prefix}_{uuid.uuid4().hex[:12]}.json"


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


def _actor_from_headers(x_actor: str | None) -> str:
    a = (x_actor or os.environ.get("RULE_CHANGE_ACTOR") or "api").strip()
    return a[:256] if a else "api"


@router.get("/change-log")
async def get_rule_change_log(
    limit: int = Query(default=100, ge=1, le=2000),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
):
    """Recent rule pack mutations (append-only JSONL under rules_path)."""
    _ = _actor_from_headers(x_actor)
    p = _change_log_path()
    if not p.is_file():
        return {"items": [], "path": str(p)}
    lines = p.read_text(encoding="utf-8").splitlines()
    tail = lines[-limit:] if len(lines) > limit else lines
    items: list[dict[str, Any]] = []
    for line in reversed(tail):
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"items": items, "path": str(p), "count": len(items)}


@router.get("")
async def list_rule_packs():
    return {"packs": _read_all_packs()}


@router.get("/vertical-packs")
async def list_vertical_pack_catalog():
    return {"vertical_packs": list_vertical_packs()}


@router.post("/vertical-packs/{vertical_name}/install", status_code=201)
async def install_vertical_pack(
    vertical_name: str,
    overwrite: bool = False,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    _admin=Depends(require_role("admin")),
):
    pack = get_vertical_pack(vertical_name)
    if not pack:
        raise HTTPException(404, f"unknown vertical pack '{vertical_name}'")
    vertical_id = _slugify_pack_name(vertical_name)
    existing_path: Path | None = None
    existing_file = ""
    for name, path in _list_pack_paths().items():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if str(data.get("__vertical_id", "")) == vertical_id:
            existing_path = path
            existing_file = name
            break
    if existing_path and not overwrite:
        raise HTTPException(409, f"pack '{existing_file}' already exists; pass overwrite=true to replace")
    errors = _validate_rule_pack(pack)
    if errors:
        raise HTTPException(422, detail={"validation_errors": errors})
    payload = dict(pack)
    payload["__vertical_id"] = vertical_id
    fpath = existing_path or _new_pack_path("vertical")
    fpath.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    load_rules()
    _append_rule_change(
        "install_vertical",
        fpath.name,
        actor=_actor_from_headers(x_actor),
        detail={"vertical": vertical_name.lower(), "overwrite": overwrite},
    )
    return {"installed": fpath.name, "vertical": vertical_name.lower(), "rules": len(pack.get("rules", []))}


@router.get("/{filename}")
async def get_rule_pack(filename: str):
    fpath = _existing_pack_path(filename)
    data = json.loads(fpath.read_text(encoding="utf-8"))
    data["_file"] = fpath.name
    return data


@router.post("", status_code=201)
async def create_rule_pack(
    body: RulePackIn,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    _admin=Depends(require_role("admin")),
):
    slug = _slugify_pack_name(body.name)
    for path in _list_pack_paths().values():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        existing_name = str(data.get("name", "")).strip().lower().replace(" ", "_")
        if existing_name == slug:
            raise HTTPException(409, f"pack name '{body.name}' already exists")
    pack = {
        "version": 1,
        "name": body.name,
        "rules": [_rule_to_dict(r) for r in body.rules],
        "tag_rules": [_tag_rule_to_dict(r) for r in body.tag_rules],
        "canary_percent": body.canary_percent,
        "effective_at": body.effective_at,
        "approved_by": body.approved_by,
    }
    errors = _validate_rule_pack(pack)
    if errors:
        raise HTTPException(422, detail={"validation_errors": errors})
    fpath = _new_pack_path("pack")
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    _append_rule_change("create", fpath.name, actor=_actor_from_headers(x_actor), detail={"name": body.name})
    return {"file": fpath.name, "pack": pack}


@router.put("/{filename}")
async def update_rule_pack(
    filename: str,
    body: RulePackIn,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    _admin=Depends(require_role("admin")),
):
    fpath = _existing_pack_path(filename)
    pack = {
        "version": 1,
        "name": body.name,
        "rules": [_rule_to_dict(r) for r in body.rules],
        "tag_rules": [_tag_rule_to_dict(r) for r in body.tag_rules],
        "canary_percent": body.canary_percent,
        "effective_at": body.effective_at,
        "approved_by": body.approved_by,
    }
    errors = _validate_rule_pack(pack)
    if errors:
        raise HTTPException(422, detail={"validation_errors": errors})
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    _append_rule_change(
        "update",
        filename,
        actor=_actor_from_headers(x_actor),
        detail={"name": body.name, "rule_count": len(pack.get("rules", []))},
    )
    return {"file": filename, "pack": pack}


@router.delete("/{filename}")
async def delete_rule_pack(
    filename: str,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    _admin=Depends(require_role("admin")),
):
    fpath = _existing_pack_path(filename)
    fpath.unlink()
    load_rules()
    _append_rule_change("delete", filename, actor=_actor_from_headers(x_actor))
    return {"deleted": filename}


@router.post("/{filename}/rules")
async def add_rule(
    filename: str,
    body: RuleIn,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    _admin=Depends(require_role("admin")),
):
    fpath = _existing_pack_path(filename)
    pack = json.loads(fpath.read_text(encoding="utf-8"))
    if not body.id:
        body.id = f"rule_{uuid.uuid4().hex[:8]}"
    pack.setdefault("rules", []).append(_rule_to_dict(body))
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    _append_rule_change("add_rule", filename, actor=_actor_from_headers(x_actor), detail={"rule_id": body.id})
    return {"added": body.id}


class RulePackMode(BaseModel):
    mode: str


@router.put("/{filename}/mode")
async def set_pack_mode(
    filename: str,
    body: RulePackMode,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    _admin=Depends(require_role("admin")),
):
    """Set a rule pack to active, shadow, or disabled mode."""
    fpath = _existing_pack_path(filename)
    if body.mode not in ("active", "shadow", "disabled"):
        raise HTTPException(400, "mode must be 'active', 'shadow', or 'disabled'")
    pack = json.loads(fpath.read_text(encoding="utf-8"))
    pack["mode"] = body.mode
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    _append_rule_change("set_mode", filename, actor=_actor_from_headers(x_actor), detail={"mode": body.mode})
    return {"file": filename, "mode": body.mode}


@router.delete("/{filename}/rules/{rule_id}")
async def remove_rule(
    filename: str,
    rule_id: str,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    _admin=Depends(require_role("admin")),
):
    fpath = _existing_pack_path(filename)
    pack = json.loads(fpath.read_text(encoding="utf-8"))
    original = len(pack.get("rules", []))
    pack["rules"] = [r for r in pack.get("rules", []) if r.get("id") != rule_id]
    if len(pack["rules"]) == original:
        raise HTTPException(404, f"rule '{rule_id}' not found")
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    _append_rule_change("remove_rule", filename, actor=_actor_from_headers(x_actor), detail={"rule_id": rule_id})
    return {"deleted": rule_id}


@router.post("/shadow/reload")
async def reload_shadow_rules(_admin=Depends(require_role("admin"))):
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
