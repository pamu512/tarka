"""Silver JSONL event_type is shape, not the closed six."""

from __future__ import annotations

import json
from pathlib import Path

import check_silver_features as silver


def _write(tmp_path: Path, event_type: str) -> Path:
    p = tmp_path / "rows.jsonl"
    p.write_text(
        json.dumps({"tenant_id": "t", "entity_id": "e", "event_type": event_type}) + "\n",
        encoding="utf-8",
    )
    return p


def test_refund_is_not_a_violation(tmp_path: Path) -> None:
    assert silver.main(["--input", str(_write(tmp_path, "refund"))]) == 0


def test_bad_shape_is_a_violation(tmp_path: Path) -> None:
    assert silver.main(["--input", str(_write(tmp_path, "Refund"))]) == 1
