"""Subset matching for EvidenceManifest trace steps and audit ``step_trace`` rows."""

from __future__ import annotations

from typing import Any, Mapping


def normalize_keys(obj: Any) -> Any:
    """Best-effort camelCase → snake_case for proto-JSON and audit blobs."""
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            nk = _to_snake(str(k))
            out[nk] = normalize_keys(v)
        return out
    if isinstance(obj, list):
        return [normalize_keys(x) for x in obj]
    return obj


def _to_snake(name: str) -> str:
    if "_" in name:
        return name
    out: list[str] = []
    i = 0
    while i < len(name):
        c = name[i]
        if c.isupper() and i > 0 and (
            not name[i - 1].isupper()
            or (i + 1 < len(name) and name[i + 1].islower())
        ):
            out.append("_")
        out.append(c.lower())
        i += 1
    return "".join(out)


def _mapping_subset(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    for k, ev in expected.items():
        av = actual.get(k)
        if isinstance(ev, Mapping) and isinstance(av, Mapping):
            if not _mapping_subset(ev, av):
                return False
        elif isinstance(ev, list) and isinstance(av, list):
            if ev != av:
                return False
        elif av != ev:
            return False
    return True


def step_matches(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    """True if *actual* contains every key/value from *expected* (recursive for dict values)."""
    exp = normalize_keys(expected)
    act = normalize_keys(actual)
    if not isinstance(exp, Mapping) or not isinstance(act, Mapping):
        return False
    return _mapping_subset(dict(exp), dict(act))


def extract_manifest_steps(manifest: Any) -> list[dict[str, Any]]:
    """Return trace steps as plain dicts (legacy nested ``trace.steps`` or wire ``trace`` repeated field)."""
    if manifest is None:
        return []

    steps_iter = None
    if hasattr(manifest, "trace"):
        tr = manifest.trace
        if hasattr(tr, "steps"):
            steps_iter = tr.steps
        else:
            steps_iter = tr

    if steps_iter is not None:
        out: list[dict[str, Any]] = []
        for s in steps_iter:
            operator = ""
            if hasattr(s, "operator"):
                operator = getattr(s, "operator", "") or ""
            elif hasattr(s, "logic_operator"):
                operator = getattr(s, "logic_operator", "") or ""
            out.append(
                {
                    "rule_id": getattr(s, "rule_id", "") or "",
                    "logic_operator": operator,
                    "operands": list(getattr(s, "operands", []) or []),
                    "result": bool(getattr(s, "result", False)),
                    "state_snapshot": dict(getattr(s, "state_snapshot", {}) or {}),
                    "otel_trace_id": getattr(s, "otel_trace_id", "") or "",
                }
            )
        return out

    if isinstance(manifest, Mapping):
        m = normalize_keys(manifest)
        trace = m.get("trace")
        if isinstance(trace, Mapping):
            steps = trace.get("steps")
            if isinstance(steps, list):
                return [dict(normalize_keys(x)) for x in steps if isinstance(x, Mapping)]
        if isinstance(trace, list):
            return [dict(normalize_keys(x)) for x in trace if isinstance(x, Mapping)]
        return []
    return []


def match_expected_steps(
    actual_steps: list[Mapping[str, Any]],
    expected_steps: list[Mapping[str, Any]],
    *,
    ordered: bool,
) -> tuple[bool, str]:
    """Match each expected pattern against actual steps (subset per step)."""
    if not expected_steps:
        return True, ""
    cur = 0
    for i, exp in enumerate(expected_steps):
        found_at: int | None = None
        scan_range = range(cur, len(actual_steps)) if ordered else range(len(actual_steps))
        for j in scan_range:
            if step_matches(exp, actual_steps[j]):
                found_at = j
                break
        if found_at is None:
            return False, f"expected step #{i} not found: {exp!r}"
        if ordered:
            cur = found_at + 1
    return True, ""
