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
