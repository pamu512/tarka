from __future__ import annotations
from fastapi import HTTPException

"""Versioned capability contract and breaking-change guardrails."""

def _major(version: str) -> int:
    v = (version or "0.0.0").strip().lstrip("v")
    part = v.split(".", 1)[0]
    try:
        return int(part)
    except ValueError:
        return 0


def assert_contract_compatible(*, plugin_contract: str, server_contract: str) -> None:
    """Reject plugins whose **major** contract version does not match the server (breaking-change guard)."""
    pm = _major(plugin_contract)
    sm = _major(server_contract)
    if pm != sm:
        raise HTTPException(
            status_code=400,
            detail=f"contract_major_mismatch: plugin={plugin_contract} server={server_contract}",
        )


def capability_matrix_ok(
    *,
    required_capabilities: dict[str, str],
    offered: dict[str, str],
) -> tuple[bool, list[str]]:
    """Return (ok, missing_keys) if ``offered`` satisfies ``required_capabilities``."""
    missing: list[str] = []
    for k, need in required_capabilities.items():
        got = offered.get(k)
        if got is None:
            missing.append(k)
        elif str(got) != str(need):
            missing.append(f"{k}(want={need},got={got})")
    return (len(missing) == 0, missing)
