"""RAG matrix compile + pre-LLM systemic resolution for the trend agent."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

MetricKey = Literal["sub_1min_velocity", "failed_auth_velocity", "sub_24h_velocity"]
Disposition = Literal["RESOLVED_SYSTEMIC", "NEEDS_LLM", "ESCALATED"]


@dataclass(frozen=True)
class WindowStat:
    metric_key: MetricKey
    window: str  # e.g. sub_1min | sub_24h | seasonal_historical_3y
    observed: float
    baseline_mean: float
    baseline_std: float
    z_score: float | None = None

    def with_z(self) -> WindowStat:
        if self.z_score is not None:
            return self
        std = self.baseline_std if self.baseline_std > 1e-9 else 1e-9
        z = (self.observed - self.baseline_mean) / std
        return WindowStat(
            metric_key=self.metric_key,
            window=self.window,
            observed=self.observed,
            baseline_mean=self.baseline_mean,
            baseline_std=self.baseline_std,
            z_score=z,
        )


@dataclass
class HilOverride:
    tenant_id: str
    entity_id: str
    override_type: str
    scope_key: str = ""
    analyst_rationale: str = ""


@dataclass
class RagMatrix:
    tenant_id: str
    entity_id: str
    region_code: str = ""
    windows: list[WindowStat] = field(default_factory=list)
    hil_overrides: list[HilOverride] = field(default_factory=list)
    seasonal_match: bool = False

    def max_abs_z(self) -> float:
        zs = [abs(float(w.z_score or 0.0)) for w in self.windows]
        return max(zs) if zs else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "entity_id": self.entity_id,
            "region_code": self.region_code,
            "seasonal_match": self.seasonal_match,
            "max_abs_z": self.max_abs_z(),
            "windows": [
                {
                    "metric_key": w.metric_key,
                    "window": w.window,
                    "observed": w.observed,
                    "baseline_mean": w.baseline_mean,
                    "baseline_std": w.baseline_std,
                    "z_score": w.z_score,
                }
                for w in self.windows
            ],
            "hil_overrides": [
                {
                    "override_type": h.override_type,
                    "scope_key": h.scope_key,
                    "analyst_rationale": h.analyst_rationale,
                }
                for h in self.hil_overrides
            ],
        }


def compile_rag_matrix(
    *,
    tenant_id: str,
    entity_id: str,
    region_code: str = "",
    window_rows: list[dict[str, Any]] | None = None,
    hil_overrides: list[HilOverride] | None = None,
    seasonal_match: bool | None = None,
) -> RagMatrix:
    """
    Build a multi-window velocity matrix from caller-supplied stats.

    Does not invent baselines — missing rows yield an empty matrix (max_z=0).
    """
    windows: list[WindowStat] = []
    for row in window_rows or []:
        if not isinstance(row, dict):
            continue
        mk = str(row.get("metric_key") or "").strip()
        win = str(row.get("window") or "").strip()
        if mk not in ("sub_1min_velocity", "failed_auth_velocity", "sub_24h_velocity"):
            continue
        if not win:
            continue
        try:
            observed = float(row["observed"])
            mean = float(row["baseline_mean"])
            std = float(row.get("baseline_std") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
        raw_z = row.get("z_score")
        z: float | None
        try:
            z = float(raw_z) if raw_z is not None else None
        except (TypeError, ValueError):
            z = None
        windows.append(
            WindowStat(
                metric_key=mk,  # type: ignore[arg-type]
                window=win,
                observed=observed,
                baseline_mean=mean,
                baseline_std=std,
                z_score=z,
            ).with_z()
        )

    hil = list(hil_overrides or [])
    if seasonal_match is None:
        seasonal_present = any(w.window == "seasonal_historical_3y" for w in windows)
        short_spike = any(
            w.window in ("sub_1min", "sub_24h") and abs(float(w.z_score or 0.0)) > 2.0
            for w in windows
        )
        seasonal_match = bool(seasonal_present and short_spike)

    return RagMatrix(
        tenant_id=(tenant_id or "").strip(),
        entity_id=(entity_id or "").strip(),
        region_code=(region_code or "").strip(),
        windows=windows,
        hil_overrides=hil,
        seasonal_match=bool(seasonal_match),
    )


def try_resolve_systemic(matrix: RagMatrix) -> tuple[Disposition, str]:
    """
    Pre-LLM gate: sharp short-window spikes covered by seasonal history or HIL → RESOLVED_SYSTEMIC.
    """
    short = [
        w
        for w in matrix.windows
        if w.window in ("sub_1min", "sub_24h") and abs(float(w.z_score or 0.0)) > 2.0
    ]
    if not short:
        if matrix.max_abs_z() > 4.0 and not matrix.hil_overrides and not matrix.seasonal_match:
            return "ESCALATED", "unmanaged_high_z_precheck"
        return "NEEDS_LLM", "no_short_window_spike"

    if matrix.seasonal_match:
        return "RESOLVED_SYSTEMIC", "seasonal_historical_3y_match"
    if matrix.hil_overrides:
        return "RESOLVED_SYSTEMIC", "active_hil_overrides"
    if matrix.max_abs_z() > 4.0:
        return "ESCALATED", "z_above_4_unmanaged"
    return "NEEDS_LLM", "short_spike_needs_forensic_pass"


def finite_z(value: float | None) -> float:
    if value is None or not math.isfinite(value):
        return 0.0
    return float(value)


def normalize_window_rows(raw: Any) -> list[dict[str, Any]]:
    """
    Accept only explicit window stats — never invent baselines.

    Forms:
    - list[dict] of window rows
    - dict with ``window_rows`` list
    - dict with ``metrics`` list (alias)
    """
    rows: list[Any]
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        inner = raw.get("window_rows")
        if inner is None:
            inner = raw.get("metrics")
        rows = inner if isinstance(inner, list) else []
    else:
        rows = []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mk = str(row.get("metric_key") or "").strip()
        win = str(row.get("window") or "").strip()
        if mk not in ("sub_1min_velocity", "failed_auth_velocity", "sub_24h_velocity"):
            continue
        if not win:
            continue
        try:
            observed = float(row["observed"])
            mean = float(row["baseline_mean"])
            std = float(row.get("baseline_std") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
        item: dict[str, Any] = {
            "metric_key": mk,
            "window": win,
            "observed": observed,
            "baseline_mean": mean,
            "baseline_std": std,
        }
        if row.get("z_score") is not None:
            try:
                item["z_score"] = float(row["z_score"])
            except (TypeError, ValueError):
                pass
        out.append(item)
    return out
