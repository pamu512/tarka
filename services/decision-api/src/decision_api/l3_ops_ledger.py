"""Machine-readable L3 four-week ops ledger (fail-closed; sim cannot advance)."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_LEDGER = _REPO_ROOT / "docs" / "compliance" / "l3-ops-ledger.json"

_WEEK_KEYS = ("1", "2", "3", "4")
_WEEK_BOOLS = (
    "shadow_on",
    "host_actions_logged",
    "outcomes_joined",
    "weekly_metrics",
    "ece_candidate",
    "sign_off",
)


def ledger_path() -> Path:
    override = os.environ.get("TARKA_L3_OPS_LEDGER_PATH", "").strip()
    if override:
        return Path(override)
    return _DEFAULT_LEDGER


def _empty_week() -> dict[str, Any]:
    return {
        "shadow_on": False,
        "host_actions_logged": False,
        "outcomes_joined": False,
        "weekly_metrics": False,
        "ece_candidate": False,
        "sign_off": False,
        "signed_at": None,
        "signed_by": None,
    }


def default_ledger() -> dict[str, Any]:
    return {
        "schema_id": "tarka.l3_ops_ledger/v1",
        "status": "NOT_STARTED",
        "tenant_id": None,
        "week1_start_utc": None,
        "week4_end_utc": None,
        "shadow_evaluate_enabled": False,
        "host_action_sink": None,
        "label_join_ece": False,
        "armed_at": None,
        "armed_by": None,
        "weeks": {k: _empty_week() for k in _WEEK_KEYS},
        "honesty": (
            "Sim/fixture never advances this ledger. COMPLETE only after four live "
            "weeks + Week-4 ECE on real labels. See docs/compliance/CLAIM_LOCK.md."
        ),
    }


def load_ledger() -> dict[str, Any]:
    path = ledger_path()
    if not path.is_file():
        return default_ledger()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_ledger()
    if not isinstance(data, dict):
        return default_ledger()
    out = default_ledger()
    out.update({k: data.get(k, out.get(k)) for k in out if k != "weeks"})
    weeks_in = data.get("weeks") if isinstance(data.get("weeks"), dict) else {}
    for k in _WEEK_KEYS:
        base = _empty_week()
        row = weeks_in.get(k) if isinstance(weeks_in.get(k), dict) else {}
        base.update({bk: bool(row.get(bk)) for bk in _WEEK_BOOLS})
        base["signed_at"] = row.get("signed_at")
        base["signed_by"] = row.get("signed_by")
        out["weeks"][k] = base
    out["schema_id"] = "tarka.l3_ops_ledger/v1"
    return out


def save_ledger(ledger: dict[str, Any]) -> Path:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(ledger, indent=2, sort_keys=False) + "\n"
    path.write_text(blob, encoding="utf-8")
    return path


def _recompute_status(ledger: dict[str, Any]) -> str:
    if not ledger.get("tenant_id") or not ledger.get("week1_start_utc"):
        return "NOT_STARTED"
    weeks = ledger.get("weeks") or {}
    signed = [k for k in _WEEK_KEYS if (weeks.get(k) or {}).get("sign_off")]
    w4 = weeks.get("4") or {}
    if (
        len(signed) == 4
        and w4.get("ece_candidate")
        and w4.get("sign_off")
        and ledger.get("label_join_ece")
    ):
        return "COMPLETE"
    if signed:
        return "IN_PROGRESS"
    if ledger.get("armed_at"):
        return "ARMED"
    return "NOT_STARTED"


def arm_ledger(
    *,
    tenant_id: str,
    week1_start_utc: str,
    host_action_sink: str,
    shadow_evaluate_enabled: bool,
    actor: str,
    label_join_ece: bool = False,
) -> dict[str, Any]:
    """Start the L3 clock. Does not claim COMPLETE. Rejects empty/sim tenants."""
    tid = (tenant_id or "").strip()
    sink = (host_action_sink or "").strip()
    start = (week1_start_utc or "").strip()
    errors: list[str] = []
    if not tid or tid.lower() in {"demo", "demo-tenant", "fixture", "sim", "test"}:
        errors.append("tenant_id_must_be_named_live_tenant")
    if not sink:
        errors.append("host_action_sink_required")
    if sink.lower().startswith("sim:") or "shadow_four_week_sim" in sink.lower():
        errors.append("host_action_sink_cannot_be_sim")
    try:
        d0 = date.fromisoformat(start[:10])
    except ValueError:
        errors.append("week1_start_utc_invalid")
        d0 = None
    if not shadow_evaluate_enabled:
        errors.append("shadow_evaluate_must_be_enabled")
    if errors:
        return {
            "ok": False,
            "blockers": errors,
            "ledger": load_ledger(),
        }
    assert d0 is not None
    ledger = default_ledger()
    ledger["tenant_id"] = tid
    ledger["week1_start_utc"] = d0.isoformat()
    ledger["week4_end_utc"] = (d0 + timedelta(days=27)).isoformat()
    ledger["host_action_sink"] = sink
    ledger["shadow_evaluate_enabled"] = True
    ledger["label_join_ece"] = bool(label_join_ece)
    ledger["armed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    ledger["armed_by"] = (actor or "operator").strip()[:128] or "operator"
    ledger["status"] = "ARMED"
    save_ledger(ledger)
    return {"ok": True, "blockers": [], "ledger": ledger}


def sign_week(
    *,
    week: int,
    checklist: dict[str, bool],
    actor: str,
) -> dict[str, Any]:
    """Sign a live week. Week 4 requires ece_candidate + label_join_ece on ledger."""
    if week not in (1, 2, 3, 4):
        return {
            "ok": False,
            "blockers": ["week_must_be_1_to_4"],
            "ledger": load_ledger(),
        }
    ledger = load_ledger()
    if ledger.get("status") == "NOT_STARTED" or not ledger.get("tenant_id"):
        return {
            "ok": False,
            "blockers": ["ledger_not_armed"],
            "ledger": ledger,
        }
    key = str(week)
    row = deepcopy(ledger["weeks"][key])
    for bk in _WEEK_BOOLS:
        if bk in checklist:
            row[bk] = bool(checklist[bk])
    required = ["shadow_on", "host_actions_logged", "outcomes_joined", "weekly_metrics"]
    blockers: list[str] = []
    for r in required:
        if not row.get(r):
            blockers.append(f"week_{week}_missing_{r}")
    if week == 4:
        # ponytail: ece_candidate on this sign is the Week-4 ECE attestation;
        # do not require a prior label_join_ece flag (that was set only after complete).
        if not row.get("ece_candidate"):
            blockers.append("week_4_requires_ece_candidate")
    if not checklist.get("sign_off"):
        blockers.append("sign_off_required")
    if blockers:
        return {"ok": False, "blockers": blockers, "ledger": ledger}
    row["sign_off"] = True
    row["signed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    row["signed_by"] = (actor or "operator").strip()[:128] or "operator"
    ledger["weeks"][key] = row
    if week == 4 and row.get("ece_candidate"):
        ledger["label_join_ece"] = True
    ledger["status"] = _recompute_status(ledger)
    save_ledger(ledger)
    return {"ok": True, "blockers": [], "ledger": ledger}


def public_view(ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    led = ledger or load_ledger()
    status = _recompute_status(led)
    led = {**led, "status": status}
    return {
        **led,
        "claim_allowed": status == "COMPLETE",
        "playbook": "docs/compliance/CLAIM_LOCK.md",
        "sim_banned": "scripts/oss/shadow_four_week_sim.py never writes this ledger",
    }
