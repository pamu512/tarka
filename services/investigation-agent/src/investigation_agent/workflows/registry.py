from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

"""Load JSON workflow manifests from package data; validate ids and template params."""
_WORKFLOW_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,79}$", re.IGNORECASE)

_MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"
_WORKFLOWS: dict[str, dict[str, Any]] = {}


def _load_all() -> None:
    global _WORKFLOWS
    _WORKFLOWS = {}
    if not _MANIFEST_DIR.is_dir():
        return
    for path in sorted(_MANIFEST_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        wid = data.get("id")
        if isinstance(wid, str) and wid.strip() and _WORKFLOW_ID_RE.match(wid.strip()):
            _WORKFLOWS[wid.strip()] = data


_load_all()


def list_workflows() -> list[dict[str, str]]:
    """Catalog for GET /v1/workflows."""
    out: list[dict[str, str]] = []
    for k in sorted(_WORKFLOWS.keys()):
        v = _WORKFLOWS[k]
        out.append(
            {
                "id": k,
                "title": str(v.get("title") or k),
                "description": str(v.get("description") or ""),
            },
        )
    return out


def validate_workflow_id(raw: str | None) -> str | None:
    if raw is None or not str(raw).strip():
        return None
    s = str(raw).strip()
    if not _WORKFLOW_ID_RE.match(s):
        raise ValueError("Invalid workflow_id (use a-z, 0-9, underscore, hyphen; max 80 chars)")
    if s not in _WORKFLOWS:
        raise ValueError(f"Unknown workflow_id: {s}")
    return s


def _substitute_params(template: str, merged: dict[str, Any]) -> str:
    out = template
    for key, val in merged.items():
        if not isinstance(key, str) or len(key) > 64:
            continue
        out = out.replace("{{" + key + "}}", str(val))
    out = re.sub(r"\{\{[a-zA-Z0-9_-]{1,64}\}\}", "", out)
    return out


def format_workflow_system_append(workflow_id: str, params: dict[str, Any] | None) -> str:
    wf = _WORKFLOWS[workflow_id]
    defaults = wf.get("default_params") if isinstance(wf.get("default_params"), dict) else {}
    merged: dict[str, Any] = {**defaults}
    if params:
        for k, v in params.items():
            if isinstance(k, str) and k and len(k) <= 64:
                merged[k] = v
    tmpl = str(wf.get("system_prompt_append") or "")
    body = _substitute_params(tmpl, merged)
    title = str(wf.get("title") or workflow_id)
    return (
        f"\n\nACTIVE WORKFLOW — **{title}** (`{workflow_id}`):\n"
        f"{body}\n"
        f"Follow this workflow unless the user explicitly redirects; still ground factual statements in tools.\n"
    )


def workflows_catalog_fingerprint() -> str:
    """Short stable id over shipped workflow manifest set + text."""
    h = hashlib.sha256()
    for k in sorted(_WORKFLOWS.keys()):
        h.update(k.encode())
        h.update(b"\0")
        h.update(json.dumps(_WORKFLOWS[k], sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def normalize_workflow_params(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Clamp size for chat requests (abuse resistance)."""
    if not raw:
        return {}
    if len(raw) > 24:
        raise ValueError("workflow_params: too many keys (max 24)")
    out: dict[str, Any] = {}
    for i, (k, v) in enumerate(raw.items()):
        if i >= 24:
            break
        if not isinstance(k, str) or not k.strip() or len(k) > 64:
            continue
        if isinstance(v, (str, int, float, bool)):
            s = str(v) if not isinstance(v, bool) else ("true" if v else "false")
            out[k.strip()[:64]] = s[:2000]
        elif v is None:
            out[k.strip()[:64]] = ""
    return out
