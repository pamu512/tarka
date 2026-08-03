#!/usr/bin/env python3
"""Validate golden evaluate / device_context fixtures (Wave A).

Checks:
1. JSON Schema structural rules for device-context + fraud-event envelopes
2. Pydantic ``EvaluateRequest`` / ``DeviceContextIn`` parse (decision-api on path)

Exit 0 on success. Used by ``make contract-check`` and CI audit-stubs.

Usage (repo root)::

  python3 infra/scripts/ci/validate_golden_evaluate_contracts.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[3]
_GOLDEN = _REPO / "contracts" / "golden"
_SCHEMA = _REPO / "contracts" / "json-schema"
_DEC_SRC = _REPO / "services" / "decision-api" / "src"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _require_object(data: Any, label: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        _fail(f"{label}: root must be object")
    return data


def validate_device_context(data: dict[str, Any], *, label: str) -> None:
    schema = _load(_SCHEMA / "device-context.json")
    required = schema.get("required") or []
    for key in required:
        if key not in data:
            _fail(f"{label}: missing required field {key!r}")
    platform = data.get("platform")
    allowed = (schema.get("properties") or {}).get("platform", {}).get("enum") or []
    if allowed and platform not in allowed:
        _fail(f"{label}: platform {platform!r} not in {allowed}")
    signals = data.get("signals")
    if not isinstance(signals, dict):
        _fail(f"{label}: signals must be object")
    # additionalProperties: false on device-context root
    known = set((schema.get("properties") or {}).keys())
    extra = set(data.keys()) - known
    if extra:
        _fail(f"{label}: unexpected keys {sorted(extra)}")


def validate_fraud_event(data: dict[str, Any], *, label: str) -> None:
    schema = _load(_SCHEMA / "fraud-event.json")
    for key in schema.get("required") or []:
        if key not in data:
            _fail(f"{label}: missing required field {key!r}")
    event_type = data.get("event_type")
    allowed = (schema.get("properties") or {}).get("event_type", {}).get("enum") or []
    if allowed and event_type not in allowed:
        _fail(f"{label}: event_type {event_type!r} not in {allowed}")
    known = set((schema.get("properties") or {}).keys())
    extra = set(data.keys()) - known
    if extra:
        _fail(f"{label}: unexpected keys {sorted(extra)}")
    dc = data.get("device_context")
    if dc is not None:
        if not isinstance(dc, dict):
            _fail(f"{label}: device_context must be object or null")
        validate_device_context(dc, label=f"{label}.device_context")


def validate_pydantic_parse(evaluate: dict[str, Any], device: dict[str, Any]) -> None:
    if str(_DEC_SRC) not in sys.path:
        sys.path.insert(0, str(_DEC_SRC))
    try:
        from decision_api.schemas import DeviceContextIn, EvaluateRequest
    except Exception as exc:  # pragma: no cover
        _fail(f"cannot import decision_api.schemas: {exc}")
    try:
        DeviceContextIn.model_validate(device)
        EvaluateRequest.model_validate(evaluate)
    except Exception as exc:
        _fail(f"pydantic parse failed: {exc}")


def main() -> int:
    device_path = _GOLDEN / "device-context-web.v1.json"
    evaluate_path = _GOLDEN / "evaluate-request-minimal.v1.json"
    if not device_path.is_file():
        _fail(f"missing {device_path}")
    if not evaluate_path.is_file():
        _fail(f"missing {evaluate_path}")

    device = _require_object(_load(device_path), device_path.name)
    evaluate = _require_object(_load(evaluate_path), evaluate_path.name)

    validate_device_context(device, label=device_path.name)
    validate_fraud_event(evaluate, label=evaluate_path.name)

    # Nested device_context must match the standalone golden (drift guard).
    nested = evaluate.get("device_context")
    if nested != device:
        _fail(
            "evaluate-request-minimal.v1.json device_context must equal "
            "device-context-web.v1.json (keep fixtures in sync)"
        )

    validate_pydantic_parse(evaluate, device)
    print(
        f"OK: validated golden evaluate/device_context fixtures under {_GOLDEN.relative_to(_REPO)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
