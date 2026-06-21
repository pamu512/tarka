#!/usr/bin/env python3
"""Drift gate: default deployment profile manifest vs Helm values and hardening overlay."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[3]
_MANIFEST = _REPO / "deploy" / "profiles" / "default-deployment-profile.yaml"
_HELM_VALUES = _REPO / "deploy" / "helm" / "fraud-stack" / "values.yaml"
_HARDENING = _REPO / "deploy" / "docker-compose.production-hardening.yml"

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML required: pip install pyyaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root must be mapping")
    return data


def _helm_get(values: dict[str, Any], dotted: str) -> Any:
    cur: Any = values
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _parse_compose_service_env(compose: dict[str, Any], service: str) -> dict[str, str]:
    services = compose.get("services") or {}
    if not isinstance(services, dict):
        return {}
    block = services.get(service) or {}
    if not isinstance(block, dict):
        return {}
    env = block.get("environment") or {}
    out: dict[str, str] = {}
    if isinstance(env, dict):
        for key, value in env.items():
            out[str(key)] = str(value)
    return out


def _check_helm_contract(manifest: dict[str, Any], values: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    contract = manifest.get("helm_contract") or {}
    if not isinstance(contract, dict):
        return ["helm_contract must be a mapping"]
    for section, expected_fields in contract.items():
        if not isinstance(expected_fields, dict):
            errors.append(f"helm_contract.{section} must be a mapping")
            continue
        for key, expected in expected_fields.items():
            actual = _helm_get(values, f"{section}.{key}")
            if actual != expected:
                errors.append(
                    f"helm drift: values.yaml {section}.{key}={actual!r} expected {expected!r}",
                )
    return errors


def _check_compose_hardening(manifest: dict[str, Any], compose: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected_services = manifest.get("compose_production_hardening") or {}
    if not isinstance(expected_services, dict):
        return ["compose_production_hardening must be a mapping"]
    for service, expected_env in expected_services.items():
        if not isinstance(expected_env, dict):
            errors.append(f"compose_production_hardening.{service} must be a mapping")
            continue
        actual_env = _parse_compose_service_env(compose, str(service))
        for key, expected in expected_env.items():
            actual = actual_env.get(str(key))
            if actual != str(expected):
                errors.append(
                    f"compose hardening drift: {service}.{key}={actual!r} expected {expected!r}",
                )
    return errors


def _check_gate_scripts(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    gates = manifest.get("ci_policy_gates") or []
    if not isinstance(gates, list):
        return ["ci_policy_gates must be a list"]
    for item in gates:
        if not isinstance(item, dict):
            errors.append("ci_policy_gates entries must be mappings")
            continue
        script = str(item.get("script") or "").strip()
        if not script:
            errors.append(f"ci_policy_gates entry missing script: {item!r}")
            continue
        path = _REPO / script
        if not path.is_file():
            errors.append(f"ci_policy_gates script not found: {script}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=_MANIFEST)
    parser.add_argument("--helm-values", type=Path, default=_HELM_VALUES)
    parser.add_argument("--hardening-compose", type=Path, default=_HARDENING)
    args = parser.parse_args()

    if yaml is None:
        print("FAIL: PyYAML not installed (pip install pyyaml)", file=sys.stderr)
        return 1

    errors: list[str] = []
    try:
        manifest = _load_yaml(args.manifest)
        values = _load_yaml(args.helm_values)
        hardening = _load_yaml(args.hardening_compose)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    errors.extend(_check_gate_scripts(manifest))
    errors.extend(_check_helm_contract(manifest, values))
    errors.extend(_check_compose_hardening(manifest, hardening))

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1

    profile_id = manifest.get("profile_id", "default")
    print(f"OK: deployment profile manifest '{profile_id}' — no drift detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
