"""Build merged PLG industry sandbox rule pack (no I/O)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from decision_api.json_rules import SANDBOX_PLG_INDUSTRY_SOURCE_FILE
from decision_api.rule_compiler_api import compile_visual_ast_pack_dict
from decision_api.rule_pack_validation import validate_rule_pack

PLG_BUNDLE_KEY = "plg_industry_v1"


def merged_pack_fingerprint(pack: dict[str, Any]) -> str:
    rid = sorted(str(r.get("id") or "") for r in (pack.get("rules") or []))
    basis = json.dumps({"rules": rid, "tag_rules": pack.get("tag_rules") or []}, sort_keys=True)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def build_merged_plg_industry_pack() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Return ``(merged_runtime_pack, per_template_compiled_without_meta, template_keys)``."""
    from tarka_core.templates import list_industry_template_items

    all_rules: list[dict[str, Any]] = []
    all_tag_rules: list[dict[str, Any]] = []
    per_template: dict[str, Any] = {}
    keys: list[str] = []

    for template_key, ast in list_industry_template_items():
        keys.append(template_key)
        compiled = compile_visual_ast_pack_dict(ast)
        compiled = {k: v for k, v in compiled.items() if k != "compiled_from"}
        per_template[template_key] = compiled
        all_rules.extend(compiled.get("rules") or [])
        all_tag_rules.extend(compiled.get("tag_rules") or [])

    merged: dict[str, Any] = {
        "version": 1,
        "name": "PLG Industry Starters (Sandbox)",
        "mode": "active",
        "approved_by": "sandbox_bootstrap",
        "rules": all_rules,
        "tag_rules": all_tag_rules,
        "_source_file": SANDBOX_PLG_INDUSTRY_SOURCE_FILE,
    }
    errs = validate_rule_pack(merged)
    if errs:
        raise ValueError("merged_pack_validation_failed:" + "; ".join(errs))
    return merged, per_template, keys
