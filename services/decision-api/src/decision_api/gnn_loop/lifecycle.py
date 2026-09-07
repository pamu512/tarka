"""Promote-shaped graph-risk challenger lifecycle (Option B+C).

Train uses fixed gnn_loop recipe. Enable-shadow only when serve_allowed.
Live customer effect remains pack Observe→Promote only.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from decision_api.gnn_loop.export import export_labeled_rows, write_export_jsonl
from decision_api.gnn_loop.receipts import load_receipts
from decision_api.gnn_loop.train import (
    load_gate_artifact,
    train_and_gate,
    write_gate_artifact,
)
from decision_api.y_label_store import _data_dir, _file_token

SCHEMA_ID = "tarka.graph_risk_lifecycle/v1"


class SidecarLifecycleError(Exception):
    def __init__(self, code: str, *, http_status: int = 400, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.http_status = http_status
        self.detail = detail or code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lifecycle_path(tenant_id: str) -> Path:
    token = _file_token(tenant_id)
    base = _data_dir()
    target = (base / f"graph_risk_lifecycle_{token}.json").resolve()
    if target.parent != base or target.suffix != ".json":
        raise SidecarLifecycleError(
            "bad_path", http_status=400, detail="lifecycle path"
        )
    return target


def load_lifecycle(tenant_id: str) -> dict[str, Any]:
    path = _lifecycle_path(tenant_id)
    if not path.is_file():
        return {
            "schema_id": SCHEMA_ID,
            "tenant_id": (tenant_id or "").strip(),
            "state": "collecting",
            "shadow_url": "",
            "shadow_enabled": False,
            "gnn_claim_allowed": False,
            "live_effect": "pack_promote_only",
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "schema_id": SCHEMA_ID,
            "tenant_id": (tenant_id or "").strip(),
            "state": "collecting",
            "shadow_url": "",
            "shadow_enabled": False,
            "gnn_claim_allowed": False,
            "live_effect": "pack_promote_only",
        }
    if not isinstance(raw, dict):
        raise SidecarLifecycleError("bad_lifecycle", http_status=500)
    raw.setdefault("schema_id", SCHEMA_ID)
    raw.setdefault("gnn_claim_allowed", False)
    raw.setdefault("live_effect", "pack_promote_only")
    return raw


def save_lifecycle(tenant_id: str, blob: dict[str, Any]) -> dict[str, Any]:
    path = _lifecycle_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(blob)
    payload["schema_id"] = SCHEMA_ID
    payload["tenant_id"] = (tenant_id or "").strip()
    payload["gnn_claim_allowed"] = False
    payload["live_effect"] = "pack_promote_only"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def default_gate_path() -> Path:
    env = os.environ.get("GNN_LOOP_GATE_PATH", "").strip()
    if env:
        return Path(env)
    return _data_dir() / "gnn_serve_gate.json"


def default_export_path(tenant_id: str) -> Path:
    token = _file_token(tenant_id)
    return _data_dir() / f"graph_risk_export_{token}.jsonl"


def run_export(tenant_id: str, *, actor: str = "") -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    if not tid:
        raise SidecarLifecycleError("missing_tenant", http_status=400)
    rows = export_labeled_rows(tid, load_receipts(tid))
    out = write_export_jsonl(rows, default_export_path(tid))
    life = load_lifecycle(tid)
    life["state"] = (
        "ready" if sum(1 for r in rows if r.get("trainable")) >= 8 else "collecting"
    )
    life["last_export_at"] = _now()
    life["last_export_rows"] = len(rows)
    life["last_actor"] = (actor or "").strip()
    save_lifecycle(tid, life)
    return {
        "ok": True,
        "export_path": str(out),
        "rows": len(rows),
        "trainable_rows": sum(1 for r in rows if r.get("trainable")),
        "lifecycle": life,
    }


def run_train(tenant_id: str, *, actor: str = "") -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    if not tid:
        raise SidecarLifecycleError("missing_tenant", http_status=400)
    who = (actor or "").strip()
    if not who:
        raise SidecarLifecycleError(
            "actor_required", http_status=400, detail="X-Actor required"
        )
    export_path = default_export_path(tid)
    if not export_path.is_file():
        run_export(tid, actor=who)
    rows: list[dict[str, Any]] = []
    for line in export_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    gate = train_and_gate(rows)
    write_gate_artifact(default_gate_path(), gate)
    life = load_lifecycle(tid)
    if gate.get("serve_allowed"):
        life["state"] = "trained"
    else:
        life["state"] = "blocked"
    life["last_train_at"] = _now()
    life["last_actor"] = who
    life["last_gate"] = {
        "serve_allowed": bool(gate.get("serve_allowed")),
        "model_auc": gate.get("model_auc"),
        "heuristic_auc": gate.get("heuristic_auc"),
        "reason": gate.get("reason"),
    }
    save_lifecycle(tid, life)
    return {"ok": True, "gate": gate, "lifecycle": life}


def enable_shadow(
    tenant_id: str,
    *,
    shadow_url: str,
    actor: str = "",
) -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    url = (shadow_url or "").strip()
    who = (actor or "").strip()
    if not tid:
        raise SidecarLifecycleError("missing_tenant", http_status=400)
    if not who:
        raise SidecarLifecycleError(
            "actor_required", http_status=400, detail="X-Actor required"
        )
    if not url:
        raise SidecarLifecycleError(
            "missing_url", http_status=400, detail="shadow_url required"
        )
    gate = load_gate_artifact(default_gate_path()) or {}
    if not gate.get("serve_allowed"):
        raise SidecarLifecycleError(
            "serve_not_allowed",
            http_status=409,
            detail="holdout gate must allow serve before Enable shadow",
        )
    life = load_lifecycle(tid)
    life["state"] = "shadow"
    life["shadow_enabled"] = True
    life["shadow_url"] = url
    life["shadow_enabled_at"] = _now()
    life["last_actor"] = who
    life["note"] = (
        "Shadow overlay intent recorded. Set GRAPH_GNN_BETA_URL to this URL on graph-service "
        "for hops to call the scorer. Live FLAG/REVIEW still requires a Promoted pack."
    )
    save_lifecycle(tid, life)
    return {"ok": True, "lifecycle": life, "gnn_claim_allowed": False}


def retire_shadow(tenant_id: str, *, actor: str = "") -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    who = (actor or "").strip()
    if not tid:
        raise SidecarLifecycleError("missing_tenant", http_status=400)
    if not who:
        raise SidecarLifecycleError(
            "actor_required", http_status=400, detail="X-Actor required"
        )
    life = load_lifecycle(tid)
    life["state"] = "retired"
    life["shadow_enabled"] = False
    life["shadow_url"] = ""
    life["retired_at"] = _now()
    life["last_actor"] = who
    save_lifecycle(tid, life)
    return {"ok": True, "lifecycle": life}
