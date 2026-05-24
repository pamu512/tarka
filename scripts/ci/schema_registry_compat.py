#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST_CONTRACT = (
    ROOT / "legacy_attic/services/event-ingest/src/event_ingest/ingest_contract.py"
)
FRAUD_EVENT_SCHEMA = ROOT / "contracts/json-schema/fraud-event.json"


def _load_frozenset_constant(module_path: Path, name: str) -> set[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    call = node.value
                    if (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id == "frozenset"
                    ):
                        if not call.args:
                            return set()
                        arg = call.args[0]
                        if isinstance(arg, (ast.Set, ast.List, ast.Tuple)):
                            values: set[str] = set()
                            for elt in arg.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    values.add(elt.value)
                            return values
    raise RuntimeError(f"Could not parse constant {name} from {module_path}")


def main() -> int:
    schema = json.loads(FRAUD_EVENT_SCHEMA.read_text(encoding="utf-8"))
    properties = set((schema.get("properties") or {}).keys())
    required = set(schema.get("required") or [])

    valid_event_types = _load_frozenset_constant(INGEST_CONTRACT, "VALID_EVENT_TYPES")
    supported_versions = _load_frozenset_constant(
        INGEST_CONTRACT, "REGISTRY_SUPPORTED_EVENT_SCHEMA_VERSIONS"
    )
    allowed_keys = _load_frozenset_constant(INGEST_CONTRACT, "_REGISTRY_ALLOWED_TOP_LEVEL_KEYS")

    core_required = {"tenant_id", "entity_id", "event_type", "payload"}
    assert core_required.issubset(required), (
        f"Schema missing required fields: {sorted(core_required - required)}"
    )
    assert schema.get("additionalProperties") is False, (
        "fraud-event schema must reject unknown top-level fields"
    )
    assert allowed_keys == properties, (
        f"Registry keys mismatch schema properties: {sorted(allowed_keys ^ properties)}"
    )

    enum_values = set(((schema.get("properties") or {}).get("event_type") or {}).get("enum") or [])
    assert valid_event_types == enum_values, (
        f"event_type enum mismatch: {sorted(valid_event_types ^ enum_values)}"
    )

    assert "1" in supported_versions, "schema registry must support event schema version '1'"
    print(
        json.dumps(
            {
                "ok": True,
                "schema": str(FRAUD_EVENT_SCHEMA.relative_to(ROOT)),
                "event_types": sorted(valid_event_types),
                "supported_versions": sorted(supported_versions),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
