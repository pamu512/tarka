"""File-backed disposition y_label store (critical regrade flag #1).

Persists trace/entity → 0/1 labels under the calibration data dir so GET
reliability-bins can join without re-POSTing the map every time.

Filenames are content-addressed (sha256 of the allowlisted tenant slug) so
filesystem paths never carry raw request tenant bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_SAFE_TENANT = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _data_dir() -> Path:
    from decision_api.config import settings

    base = os.environ.get("CALIBRATION_DATA_DIR", "").strip()
    if base:
        p = Path(base).resolve()
    else:
        p = (Path(settings.rules_path) / "calibration_data").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _tenant_slug(tenant_id: str) -> str:
    """Allowlist tenant segment — no path separators or traversal tokens."""
    raw = (tenant_id or "").strip()
    if _SAFE_TENANT.fullmatch(raw) and raw not in {".", ".."}:
        return raw
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in raw)[:120]
    if not safe or safe in {".", ".."}:
        return "default"
    return safe


def _file_token(tenant_id: str) -> str:
    """Hex digest path segment — breaks CodeQL taint from request → path."""
    slug = _tenant_slug(tenant_id)
    digest = hashlib.sha256(f"tarka.y_labels:{slug}".encode("utf-8")).hexdigest()
    if not _HEX64.fullmatch(digest):
        raise ValueError("invalid y_label file token")
    return digest


def _path(tenant_id: str) -> Path:
    token = _file_token(tenant_id)
    base = _data_dir()
    # Constant prefix + hex-only token (no user string in the join).
    target = (base / f"y_labels_{token}.json").resolve()
    if target.parent != base or target.suffix != ".json":
        raise ValueError("y_label path outside calibration data dir")
    return target


def _str_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if str(k).strip() and str(v)}


_LABEL_KINDS = frozenset(
    {"fp", "fraud", "other", "promo_abuse", "collusion", "chargeback"}
)
_LABEL_SOURCES = frozenset({"care", "finance", "crm", "evaluate"})


def _empty_records() -> dict[str, dict[str, str]]:
    return {
        "by_trace": {},
        "by_entity": {},
        "why_by_trace": {},
        "why_by_entity": {},
        "dispute_outcome_by_trace": {},
        "chargeback_class_by_trace": {},
        "label_kind_by_trace": {},
        "label_source_by_trace": {},
        "prior_override_id_by_trace": {},
        "fp_cost_by_trace": {},
    }


def load_label_records(tenant_id: str) -> dict[str, dict[str, str]]:
    """Full store including override why and late chargeback fields."""
    empty = _empty_records()
    try:
        path = _path(tenant_id)
    except ValueError:
        return empty
    if not path.is_file():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(raw, dict):
        return empty
    by_t = raw.get("by_trace") if isinstance(raw.get("by_trace"), dict) else {}
    by_e = raw.get("by_entity") if isinstance(raw.get("by_entity"), dict) else {}
    return {
        "by_trace": {str(k): str(v) for k, v in by_t.items() if str(v) in {"0", "1"}},
        "by_entity": {str(k): str(v) for k, v in by_e.items() if str(v) in {"0", "1"}},
        "why_by_trace": _str_map(raw.get("why_by_trace")),
        "why_by_entity": _str_map(raw.get("why_by_entity")),
        "dispute_outcome_by_trace": _str_map(raw.get("dispute_outcome_by_trace")),
        "chargeback_class_by_trace": _str_map(raw.get("chargeback_class_by_trace")),
        "label_kind_by_trace": {
            k: v
            for k, v in _str_map(raw.get("label_kind_by_trace")).items()
            if v in _LABEL_KINDS
        },
        "label_source_by_trace": {
            k: v
            for k, v in _str_map(raw.get("label_source_by_trace")).items()
            if v in _LABEL_SOURCES
        },
        "prior_override_id_by_trace": _str_map(raw.get("prior_override_id_by_trace")),
        "fp_cost_by_trace": _str_map(raw.get("fp_cost_by_trace")),
    }


def load_y_labels(tenant_id: str) -> dict[str, dict[str, str]]:
    rec = load_label_records(tenant_id)
    return {"by_trace": rec["by_trace"], "by_entity": rec["by_entity"]}


def merge_y_labels(
    tenant_id: str,
    *,
    by_trace: dict[str, str] | None = None,
    by_entity: dict[str, str] | None = None,
    why_by_trace: dict[str, str] | None = None,
    why_by_entity: dict[str, str] | None = None,
    dispute_outcome_by_trace: dict[str, str] | None = None,
    chargeback_class_by_trace: dict[str, str] | None = None,
    label_kind_by_trace: dict[str, str] | None = None,
    label_source_by_trace: dict[str, str] | None = None,
    prior_override_id_by_trace: dict[str, str] | None = None,
    fp_cost_by_trace: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Merge 0/1 maps plus optional why / late chargeback / frontline fields."""
    with _lock:
        cur = load_label_records(tenant_id)
        t_map = dict(cur["by_trace"])
        e_map = dict(cur["by_entity"])
        why_t = dict(cur["why_by_trace"])
        why_e = dict(cur["why_by_entity"])
        disp_t = dict(cur["dispute_outcome_by_trace"])
        cls_t = dict(cur["chargeback_class_by_trace"])
        kind_t = dict(cur["label_kind_by_trace"])
        src_t = dict(cur["label_source_by_trace"])
        ovr_t = dict(cur["prior_override_id_by_trace"])
        cost_t = dict(cur.get("fp_cost_by_trace") or {})
        added = 0
        for k, v in (by_trace or {}).items():
            key = str(k).strip()
            if key and v in {"0", "1"} and t_map.get(key) != v:
                t_map[key] = v
                added += 1
            elif key and v in {"0", "1"}:
                t_map[key] = v
        for k, v in (by_entity or {}).items():
            key = str(k).strip()
            if key and v in {"0", "1"}:
                e_map[key] = v
        for k, v in (why_by_trace or {}).items():
            key = str(k).strip()
            text = str(v).strip()
            if key and text:
                why_t[key] = text[:2000]
        for k, v in (why_by_entity or {}).items():
            key = str(k).strip()
            text = str(v).strip()
            if key and text:
                why_e[key] = text[:2000]
        for k, v in (dispute_outcome_by_trace or {}).items():
            key = str(k).strip()
            text = str(v).strip()
            if key and text:
                disp_t[key] = text[:256]
        for k, v in (chargeback_class_by_trace or {}).items():
            key = str(k).strip()
            token = str(v).strip().upper()
            if key and token in {"FRAUD", "FRIENDLY", "SERVICE", "UNKNOWN"}:
                cls_t[key] = token
        for k, v in (label_kind_by_trace or {}).items():
            key = str(k).strip()
            token = str(v).strip().lower()
            if key and token in _LABEL_KINDS:
                kind_t[key] = token
        for k, v in (label_source_by_trace or {}).items():
            key = str(k).strip()
            token = str(v).strip().lower()
            if key and token in _LABEL_SOURCES:
                src_t[key] = token
        for k, v in (prior_override_id_by_trace or {}).items():
            key = str(k).strip()
            text = str(v).strip()
            if key and text:
                ovr_t[key] = text[:256]
        for k, v in (fp_cost_by_trace or {}).items():
            key = str(k).strip()
            text = str(v).strip()
            if key and text:
                cost_t[key] = text[:512]
        payload = {
            "by_trace": t_map,
            "by_entity": e_map,
            "why_by_trace": why_t,
            "why_by_entity": why_e,
            "dispute_outcome_by_trace": disp_t,
            "chargeback_class_by_trace": cls_t,
            "label_kind_by_trace": kind_t,
            "label_source_by_trace": src_t,
            "prior_override_id_by_trace": ovr_t,
            "fp_cost_by_trace": cost_t,
        }
        path = _path(tenant_id)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "tenant_id": tenant_id,
            "trace_labels": len(t_map),
            "entity_labels": len(e_map),
            "updated": added,
            "by_trace": t_map,
            "by_entity": e_map,
            "why_by_trace": why_t,
            "why_by_entity": why_e,
            "dispute_outcome_by_trace": disp_t,
            "chargeback_class_by_trace": cls_t,
            "label_kind_by_trace": kind_t,
            "label_source_by_trace": src_t,
            "prior_override_id_by_trace": ovr_t,
            "fp_cost_by_trace": cost_t,
        }
