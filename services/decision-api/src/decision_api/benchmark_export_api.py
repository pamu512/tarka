from __future__ import annotations


def _ensure_shared_on_path() -> None:
    import sys
    from pathlib import Path as _Path

    for _parent in _Path(__file__).resolve().parents:
        _candidate = _parent / "shared"
        if _candidate.is_dir() and (_candidate / "observability.py").is_file():
            p = str(_candidate)
            if p not in sys.path:
                sys.path.insert(0, p)
            return


import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from decision_api.config import settings
from decision_api.experiment_api import append_experiment_record

_ensure_shared_on_path()
from auth_rbac import require_role  # noqa: E402

router = APIRouter(prefix="/v1/simulation/benchmark", tags=["simulation"])

SCHEMA_ID = "tarka.tenant_benchmark_export/v1"
DEFAULT_SEED = 42
DEFAULT_VERTICALS = ("fintech", "ecommerce", "gaming")


def _exports_dir() -> Path:
    base = Path(settings.rules_path)
    base.mkdir(parents=True, exist_ok=True)
    d = base / "tenant_benchmark_exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tenant_file(tenant_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in tenant_id.strip())[
        :128
    ]
    if not safe:
        raise HTTPException(status_code=400, detail="tenant_id required")
    root = _exports_dir().resolve()
    path = (root / f"{safe}.jsonl").resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=400, detail="invalid tenant_id")
    return path


def _load_latest_export(tenant_id: str) -> dict[str, Any] | None:
    path = _tenant_file(tenant_id)
    if not path.is_file():
        return None
    last: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("tenant_id") == tenant_id:
            last = row
    return last


def _append_export(record: dict[str, Any]) -> dict[str, Any]:
    path = _tenant_file(str(record.get("tenant_id") or ""))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return record


def _run_vertical_benchmark(
    tenant_id: str,
    *,
    seed: int = DEFAULT_SEED,
    scenario: str = "baseline",
    verticals: tuple[str, ...] = DEFAULT_VERTICALS,
) -> dict[str, Any]:
    import random

    from decision_api.simulation_api import _eval_with_override_rules
    from decision_api.simulator import (
        SCENARIO_TEMPLATES,
        analyze_simulation,
        generate_scenario,
    )
    from decision_api.vertical_packs import get_vertical_pack

    if scenario not in SCENARIO_TEMPLATES:
        raise HTTPException(400, f"Unknown scenario: {scenario}")

    profile = SCENARIO_TEMPLATES[scenario]
    vertical_results: dict[str, Any] = {}
    for vertical in verticals:
        pack = get_vertical_pack(vertical)
        if not pack:
            raise HTTPException(404, f"Unknown vertical pack: {vertical}")
        random.seed(seed)
        events = generate_scenario(profile)
        baseline = [_eval_with_override_rules(e, []) for e in events]
        vertical_decisions = [
            _eval_with_override_rules(e, pack.get("rules", [])) for e in events
        ]
        result_base = analyze_simulation(events, baseline)
        result_vertical = analyze_simulation(events, vertical_decisions)
        n = len(events)
        delta = {
            "precision": round(result_vertical.precision - result_base.precision, 4),
            "recall": round(result_vertical.recall - result_base.recall, 4),
            "f1_score": round(result_vertical.f1_score - result_base.f1_score, 4),
            "score_separation": round(
                result_vertical.score_separation - result_base.score_separation, 2
            ),
            "false_positives": result_vertical.false_positives
            - result_base.false_positives,
            "false_negatives": result_vertical.false_negatives
            - result_base.false_negatives,
        }
        vertical_results[vertical] = {
            "events_evaluated": n,
            "delta": delta,
            "seed": seed,
        }

    artifact = {
        "schema_id": SCHEMA_ID,
        "tenant_id": tenant_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "release": "v1.2.0-day60",
        "request_template": {"scenario": scenario, "seed": seed},
        "verticals": vertical_results,
    }
    digest = hashlib.sha256(
        json.dumps(vertical_results, sort_keys=True).encode("utf-8")
    ).hexdigest()
    artifact["content_digest"] = digest
    return artifact


class BenchmarkExportTrigger(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    seed: int = Field(default=DEFAULT_SEED)
    scenario: str = Field(default="baseline", max_length=64)
    verticals: list[str] = Field(
        default_factory=lambda: list(DEFAULT_VERTICALS),
        max_length=8,
    )


@router.get("/export")
async def get_benchmark_export(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    _user=Depends(require_role("analyst")),
):
    """Tenant-scoped latest publishable vertical benchmark scorecard."""
    row = _load_latest_export(tenant_id)
    if not row:
        raise HTTPException(404, f"no benchmark export for tenant_id={tenant_id!r}")
    return row


@router.post("/export", status_code=201)
async def create_benchmark_export(
    body: BenchmarkExportTrigger,
    _admin=Depends(require_role("admin")),
):
    """Run reproducible vertical benchmark (seed 42 default) and persist tenant export."""
    verticals = (
        tuple(v.strip().lower() for v in body.verticals if str(v).strip())
        or DEFAULT_VERTICALS
    )
    artifact = _run_vertical_benchmark(
        body.tenant_id.strip(),
        seed=body.seed,
        scenario=body.scenario.strip(),
        verticals=verticals,
    )
    record = {
        "export_id": hashlib.sha256(
            json.dumps(artifact, sort_keys=True, default=str).encode()
        ).hexdigest()[:16],
        **artifact,
    }
    _append_export(record)
    append_experiment_record(
        "tenant_benchmark_export",
        scenario=body.scenario,
        population_id=body.tenant_id,
        events_evaluated=sum(
            int(v.get("events_evaluated") or 0)
            for v in artifact.get("verticals", {}).values()
            if isinstance(v, dict)
        ),
        notes="POST /v1/simulation/benchmark/export",
        meta={"seed": body.seed, "verticals": list(verticals)},
    )
    return record
