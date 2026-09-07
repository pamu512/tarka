"""Append-only evaluate receipts (JSONL). Same path hygiene as y_label_store."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from decision_api.y_label_store import _data_dir, _file_token

_lock = threading.Lock()


def _receipt_path(tenant_id: str) -> Path:
    token = _file_token(tenant_id)
    base = _data_dir()
    target = (base / f"gnn_receipts_{token}.jsonl").resolve()
    if target.parent != base or target.suffix != ".jsonl":
        raise ValueError("gnn receipt path outside calibration data dir")
    return target


def append_receipt(tenant_id: str, receipt: dict[str, Any]) -> None:
    if not isinstance(receipt, dict):
        return
    try:
        path = _receipt_path(tenant_id)
    except ValueError:
        return
    line = json.dumps(receipt, separators=(",", ":"), default=str)
    with _lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.write("\n")


def find_receipt(tenant_id: str, join_key: str) -> dict[str, Any] | None:
    """Last receipt whose ``trace_id`` or ``evaluation_token`` matches ``join_key``."""
    key = (join_key or "").strip()
    if not key:
        return None
    found: dict[str, Any] | None = None
    for row in load_receipts(tenant_id):
        if str(row.get("trace_id") or "").strip() == key:
            found = row
        elif str(row.get("evaluation_token") or "").strip() == key:
            found = row
    return found


def find_override_receipt(
    tenant_id: str, override_id: str, join_key: str = ""
) -> dict[str, Any] | None:
    """Last receipt whose ``override_id`` matches; optional same evaluate token."""
    oid = (override_id or "").strip()
    if not oid:
        return None
    key = (join_key or "").strip()
    found: dict[str, Any] | None = None
    for row in load_receipts(tenant_id):
        if str(row.get("override_id") or "").strip() != oid:
            continue
        if key and not (
            str(row.get("trace_id") or "").strip() == key
            or str(row.get("evaluation_token") or "").strip() == key
        ):
            continue
        found = row
    return found


def find_prior_receipt_for_entity(
    tenant_id: str, entity_id: str, *, exclude_trace: str = ""
) -> dict[str, Any] | None:
    """Last receipt for ``entity_id``, skipping ``exclude_trace`` (later evaluate)."""
    eid = (entity_id or "").strip()
    if not eid:
        return None
    skip = (exclude_trace or "").strip()
    found: dict[str, Any] | None = None
    for row in load_receipts(tenant_id):
        if str(row.get("entity_id") or "").strip() != eid:
            continue
        tid = str(row.get("trace_id") or "").strip()
        if skip and tid == skip:
            continue
        found = row
    return found


def load_receipts(tenant_id: str) -> list[dict[str, Any]]:
    try:
        path = _receipt_path(tenant_id)
    except ValueError:
        return []
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
    except OSError:
        return []
    return out
