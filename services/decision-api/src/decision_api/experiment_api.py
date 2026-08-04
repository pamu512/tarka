from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from decision_api.config import settings

"""Lightweight simulation experiment registry (audit trail for A/B and vertical benchmarks)."""
router = APIRouter(prefix="/v1/simulation/experiments", tags=["simulation"])

# Keep in sync with simulation_api._MIN_SIM_N (imported lazily to avoid cycles).
_DEFAULT_MIN_HOLD_OUT = 200


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
    allow_underpowered: bool = False
    minimum_recommended_events: int = _DEFAULT_MIN_HOLD_OUT


def append_experiment_record(
    experiment_type: str,
    *,
    scenario: str | None = None,
    vertical: str | None = None,
    population_id: str | None = None,
    events_evaluated: int = 0,
    notes: str | None = None,
    meta: dict[str, Any] | None = None,
    allow_underpowered: bool = False,
    minimum_recommended_events: int = _DEFAULT_MIN_HOLD_OUT,
) -> dict[str, Any]:
    min_n = max(1, int(minimum_recommended_events))
    n = int(events_evaluated)
    underpowered = n < min_n
    holdout_ok = (not underpowered) or bool(allow_underpowered)
    merged_meta = dict(meta or {})
    merged_meta.setdefault("allow_underpowered", bool(allow_underpowered))
    merged_meta.setdefault("minimum_recommended_events", min_n)
    merged_meta.setdefault("underpowered", underpowered)
    merged_meta.setdefault("holdout_ok", holdout_ok)
    # KPI-safe only when sample meets min without relying on override as "ok".
    merged_meta.setdefault("kpi_eligible", (not underpowered))
    rec = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "experiment_type": experiment_type,
        "scenario": scenario,
        "vertical": vertical,
        "population_id": population_id,
        "events_evaluated": n,
        "notes": notes,
        "allow_underpowered": bool(allow_underpowered),
        "underpowered": underpowered,
        "holdout_ok": holdout_ok,
        "kpi_eligible": not underpowered,
        "minimum_recommended_events": min_n,
        "meta": merged_meta,
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
        allow_underpowered=body.allow_underpowered,
        minimum_recommended_events=body.minimum_recommended_events,
    )


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _row_ts(row: dict[str, Any]) -> datetime | None:
    return _parse_iso(str(row.get("ts") or ""))


def list_experiment_records(
    *,
    limit: int = 50,
    experiment_type: str | None = None,
    population_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    holdout_ok: bool | None = None,
    kpi_eligible: bool | None = None,
) -> dict[str, Any]:
    """List recent experiment registry rows with optional filters (Wave B)."""
    lim = max(1, min(int(limit), 200))
    p = _path()
    if not p.is_file():
        return {
            "experiments": [],
            "filters": {
                "experiment_type": experiment_type,
                "population_id": population_id,
                "since": since,
                "until": until,
                "holdout_ok": holdout_ok,
                "kpi_eligible": kpi_eligible,
                "limit": lim,
            },
        }
    since_dt = _parse_iso(since)
    until_dt = _parse_iso(until)
    et_filter = (experiment_type or "").strip().lower() or None
    pop_filter = (population_id or "").strip() or None

    lines = p.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in reversed(lines[-2000:]):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if et_filter and str(row.get("experiment_type") or "").lower() != et_filter:
            continue
        if pop_filter is not None and str(row.get("population_id") or "") != pop_filter:
            continue
        ts = _row_ts(row)
        if since_dt and (ts is None or ts < since_dt):
            continue
        if until_dt and (ts is None or ts > until_dt):
            continue
        # Backfill holdout flags for older rows.
        n = int(row.get("events_evaluated") or 0)
        min_n = int(row.get("minimum_recommended_events") or _DEFAULT_MIN_HOLD_OUT)
        under = bool(row.get("underpowered")) if "underpowered" in row else n < min_n
        h_ok = (
            bool(row["holdout_ok"])
            if "holdout_ok" in row
            else (not under or bool(row.get("allow_underpowered")))
        )
        kpi = bool(row["kpi_eligible"]) if "kpi_eligible" in row else (not under)
        row = {
            **row,
            "underpowered": under,
            "holdout_ok": h_ok,
            "kpi_eligible": kpi,
            "minimum_recommended_events": min_n,
        }
        if holdout_ok is not None and h_ok is not holdout_ok:
            continue
        if kpi_eligible is not None and kpi is not kpi_eligible:
            continue
        out.append(row)
        if len(out) >= lim:
            break
    return {
        "experiments": out,
        "filters": {
            "experiment_type": experiment_type,
            "population_id": population_id,
            "since": since,
            "until": until,
            "holdout_ok": holdout_ok,
            "kpi_eligible": kpi_eligible,
            "limit": lim,
        },
    }


@router.get("")
async def list_experiments(
    limit: int = Query(50, ge=1, le=200),
    experiment_type: str | None = Query(None, max_length=64),
    population_id: str | None = Query(None, max_length=128),
    since: str | None = Query(None, description="ISO-8601 lower bound on ts"),
    until: str | None = Query(None, description="ISO-8601 upper bound on ts"),
    holdout_ok: bool | None = Query(
        None, description="Filter by holdout_ok (powered or override accepted)"
    ),
    kpi_eligible: bool | None = Query(
        None, description="True = events_evaluated met minimum (not underpowered)"
    ),
):
    return list_experiment_records(
        limit=limit,
        experiment_type=experiment_type,
        population_id=population_id,
        since=since,
        until=until,
        holdout_ok=holdout_ok,
        kpi_eligible=kpi_eligible,
    )
