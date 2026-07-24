from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from decision_api.config import settings

"""Lightweight simulation experiment registry (audit trail for A/B and vertical benchmarks)."""
router = APIRouter(prefix="/v1/simulation/experiments", tags=["simulation"])


def _path() -> Path:
    base = Path(settings.rules_path)
    base.mkdir(parents=True, exist_ok=True)
    return base / "experiment_registry.jsonl"


def experiment_registry_line_count() -> int:
    p = _path()
    if not p.is_file():
        return 0
    return sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())


class ExperimentRecordIn(BaseModel):
    experiment_type: str = Field(..., min_length=1, max_length=64)
    scenario: str | None = None
    vertical: str | None = None
    population_id: str | None = None
    events_evaluated: int = 0
    notes: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


def append_experiment_record(
    experiment_type: str,
    *,
    scenario: str | None = None,
    vertical: str | None = None,
    population_id: str | None = None,
    events_evaluated: int = 0,
    notes: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rec = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "experiment_type": experiment_type,
        "scenario": scenario,
        "vertical": vertical,
        "population_id": population_id,
        "events_evaluated": events_evaluated,
        "notes": notes,
        "meta": meta or {},
    }
    p = _path()
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


@router.post("", status_code=201)
async def record_experiment(body: ExperimentRecordIn):
    """Append one experiment run (JSON Lines) for governance / reproducibility."""
    return append_experiment_record(
        body.experiment_type,
        scenario=body.scenario,
        vertical=body.vertical,
        population_id=body.population_id,
        events_evaluated=body.events_evaluated,
        notes=body.notes,
        meta=body.meta,
    )


@router.get("")
async def list_experiments(limit: int = 50):
    p = _path()
    if not p.is_file():
        return {"experiments": []}
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in reversed(lines[-500:]):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= min(limit, 200):
            break
    return {"experiments": out}
